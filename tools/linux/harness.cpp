#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <memory>
#include <new>
#include <numeric>
#include <random>
#include <string>
#include <tuple>
#include <utility>
#include <vector>
#include <xmmintrin.h>

#include <faust/dsp/dsp.h>
#include <faust/dsp/llvm-dsp.h>

#include "onda_processor_abi.h"

constexpr int block_size = 256;
constexpr int sample_rate = 48000;
constexpr int input_blocks = 64;
constexpr int channels = 16;
using Ports = std::array<float*, channels>;
using Clock = std::chrono::steady_clock;

struct InputPorts {
    Ports faust;
    std::array<const void*, channels> onda;
};

struct OutputPorts {
    Ports faust;
    std::array<void*, channels> onda;
};

[[noreturn]] void fail(const std::string& message) {
    std::fprintf(stderr, "%s\n", message.c_str());
    std::exit(1);
}

struct Engine {
    std::string name;
    explicit Engine(std::string name) : name(std::move(name)) {}
    virtual ~Engine() = default;
    virtual void reset() = 0;
    virtual void compute(InputPorts& inputs, OutputPorts& outputs) = 0;
};

struct OndaEngine : Engine {
    onda_processor_init_fn init;
    onda_processor_process_fn process;
    void* state;
    void* params;
    std::align_val_t state_align;
    std::align_val_t param_align;

    OndaEngine(const char* name, onda_processor_init_fn init, onda_processor_process_fn process,
               size_t state_bytes, size_t state_alignment, size_t param_alignment,
               const unsigned char* defaults, size_t param_bytes)
        : Engine(name), init(init), process(process),
          state_align{std::max<size_t>(16, state_alignment)},
          param_align{std::max<size_t>(16, param_alignment)} {
        state = ::operator new(std::max<size_t>(1, state_bytes), state_align);
        params = ::operator new(param_bytes, param_align);
        std::memcpy(params, defaults, param_bytes);
    }

    ~OndaEngine() override {
        ::operator delete(params, param_align);
        ::operator delete(state, state_align);
    }

    void reset() override {
        if (init(params, state, ONDA_PROCESSOR_INIT_FULL, nullptr, nullptr, nullptr, nullptr,
                 nullptr) != ONDA_PROCESSOR_EXECUTION_OK) fail(name + " init failed");
    }

    void compute(InputPorts& inputs, OutputPorts& outputs) override {
        if (process(state, params, inputs.onda.data(), outputs.onda.data(), 0, block_size,
                    ONDA_PROCESSOR_FULL_BLOCK, nullptr, nullptr, nullptr, nullptr,
                    nullptr) != ONDA_PROCESSOR_EXECUTION_OK) {
            fail(name + " process failed");
        }
    }
};

struct FaustEngine : Engine {
    std::unique_ptr<dsp> instance;

    FaustEngine(const char* name, dsp* instance, int inputs, int outputs)
        : Engine(name), instance(instance) {
        if (!instance || instance->getNumInputs() != inputs || instance->getNumOutputs() != outputs) {
            fail(this->name + " has incompatible audio ports");
        }
    }

    void reset() override { instance->init(sample_rate); }
    void compute(InputPorts& inputs, OutputPorts& outputs) override {
        instance->compute(block_size, inputs.faust.data(), outputs.faust.data());
    }
};

using Engines = std::vector<std::unique_ptr<Engine>>;
#include "engines.inc"

llvm_dsp_factory* faust_factory(const char* path, const char* libraries, const char* name,
                               bool vectorize) {
    std::string error;
    const char* options[] = {"-I", libraries, "-cn", name, "-scal", "-vs", "32"};
    if (vectorize) options[4] = "-vec";
    auto* factory = createDSPFactoryFromFile(path, vectorize ? 7 : 5, options, "", error, -1);
    if (!factory) fail(std::string(name) + ": " + error);
    return factory;
}

struct Block {
    alignas(64) float data[channels][block_size];
    Ports ports() {
        Ports result;
        std::copy(std::begin(data), std::end(data), result.begin());
        return result;
    }
};

struct Error {
    double squared = 0;
    double reference_squared = 0;
    double max_absolute = 0;
    bool finite = true;

    void add(float actual, float reference) {
        finite &= std::isfinite(actual) && std::isfinite(reference);
        const double delta = std::abs(double(actual) - reference);
        squared += delta * delta;
        reference_squared += double(reference) * reference;
        max_absolute = std::max(max_absolute, delta);
    }

    double relative_rms() const {
        if (!finite) return std::numeric_limits<double>::infinity();
        if (reference_squared > 0) return std::sqrt(squared / reference_squared);
        return squared == 0 ? 0 : std::numeric_limits<double>::infinity();
    }
};

double median(std::vector<double> values) {
    std::sort(values.begin(), values.end());
    return (values[(values.size() - 1) / 2] + values[values.size() / 2]) / 2;
}

int main(int argc, char** argv) {
    if (argc != 8) fail("usage: bench DSP NAME FAUSTLIB SR48LIB ROUNDS ROUND_MS IR_DIR");
    const int rounds = std::stoi(argv[5]);
    const int round_ms = std::stoi(argv[6]);
    if (rounds < 1 || round_ms < 1) fail("rounds and round duration must be positive");
    constexpr unsigned ftz_daz = (1u << 15) | (1u << 6);
    const char* flush = std::getenv("BENCH_FLUSH_DENORMALS");
    _mm_setcsr((_mm_getcsr() & ~ftz_daz) | (flush && *flush == '1' ? ftz_daz : 0));
    Engines engines;
    add_engines(engines);
    std::vector<llvm_dsp_factory*> factories;
    const char* faust_opt = std::getenv("FAUST_OPT");
    const bool no_fast = faust_opt && std::strcmp(faust_opt, "FAUST_LLVM_NO_FM") == 0;
    for (const auto& [name, libraries, vectorize] : {
             std::tuple{"llvm-scal", argv[3], false}, std::tuple{"llvm-vec", argv[3], true},
             std::tuple{"llvm48", argv[4], false}, std::tuple{"llvm48-vec", argv[4], true}}) {
        auto* factory = faust_factory(argv[1], libraries, name, vectorize);
        const std::string label = std::string(name) + (no_fast ? "-no-fm" : "");
        if (*argv[7] && !writeDSPFactoryToIRFile(factory, std::string(argv[7]) + "/" + label + ".ll")) {
            fail(label + " IR export failed");
        }
        factories.push_back(factory);
        engines.push_back(std::make_unique<FaustEngine>(label.c_str(), factory->createDSPInstance(),
                                                        input_count, output_count));
    }

    std::vector<Block> input(input_blocks);
    uint32_t seed = 22222;
    for (auto& block : input) {
        for (auto& channel : block.data) {
            for (auto& x : channel) {
                seed = seed * 1664525u + 1013904223u;
                x = static_cast<int32_t>(seed) * (0.5f / 2147483648.0f);
            }
        }
    }
    Block output;
    OutputPorts out{output.ports(), {}};
    std::copy(out.faust.begin(), out.faust.end(), out.onda.begin());
    std::vector<InputPorts> input_ports(input_blocks);
    for (int b = 0; b < input_blocks; ++b) {
        auto& ports = input_ports[b];
        ports.faust = input[b].ports();
        std::copy(ports.faust.begin(), ports.faust.end(), ports.onda.begin());
    }

    constexpr int compare_blocks = 4 * sample_rate / block_size;
    std::vector<float> reference;
    reference.reserve(compare_blocks * output_count * block_size);
    const auto reference_engine = std::find_if(engines.begin(), engines.end(), [](const auto& engine) {
        return engine->name == "cpp-scal";
    });
    if (reference_engine == engines.end()) fail("missing reference engine");
    (*reference_engine)->reset();
    for (int b = 0; b < compare_blocks; ++b) {
        for (auto& channel : output.data) std::fill(std::begin(channel), std::end(channel), NAN);
        (*reference_engine)->compute(input_ports[b % input_blocks], out);
        for (int c = 0; c < output_count; ++c) {
            reference.insert(reference.end(), out.faust[c], out.faust[c] + block_size);
        }
    }

    std::vector<Error> errors(engines.size());
    std::vector<double> worst_channel(engines.size());
    for (size_t i = 0; i < engines.size(); ++i) {
        auto& engine = *engines[i];
        engine.reset();
        std::vector<Error> per_channel(output_count);
        size_t offset = 0;
        for (int b = 0; b < compare_blocks; ++b) {
            for (auto& channel : output.data) std::fill(std::begin(channel), std::end(channel), NAN);
            engine.compute(input_ports[b % input_blocks], out);
            for (int c = 0; c < output_count; ++c) {
                for (int j = 0; j < block_size; ++j) {
                    const float expected = reference[offset++];
                    per_channel[c].add(out.faust[c][j], expected);
                    errors[i].add(out.faust[c][j], expected);
                }
            }
        }
        for (const auto& error : per_channel) {
            worst_channel[i] = std::max(worst_channel[i], error.relative_rms());
        }
    }

    auto time_blocks = [&](Engine& e, int count, int first) {
        const auto start = Clock::now();
        for (int b = 0; b < count; ++b) e.compute(input_ports[(first + b) % input_blocks], out);
        return std::chrono::duration<double, std::nano>(Clock::now() - start).count();
    };
    double worst_block_ns = 0;
    for (auto& e : engines) {
        e->reset();
        time_blocks(*e, 2000, 0);
        worst_block_ns = std::max(worst_block_ns, time_blocks(*e, 300, 0) / 300);
    }
    const int count = std::max(50, int(1e6 * round_ms / worst_block_ns));
    std::vector<size_t> order(engines.size());
    std::iota(order.begin(), order.end(), 0);
    std::mt19937 generator(12345);
    std::vector<std::vector<double>> times(engines.size());
    for (int round = 0; round < rounds; ++round) {
        std::shuffle(order.begin(), order.end(), generator);
        for (size_t i : order) {
            times[i].push_back(time_blocks(*engines[i], count, round * 7) / (count * double(block_size)));
        }
    }

    for (size_t i = 0; i < engines.size(); ++i) {
        const double center = median(times[i]);
        auto deviations = times[i];
        for (double& x : deviations) x = std::abs(x - center);
        const auto& error = errors[i];
        std::printf("%s\t%s\t%.5f\t%.5f\t%.7g\t%.7g\t%.7g\t%d\t%.7g\n",
                    argv[2], engines[i]->name.c_str(), center, median(deviations), error.max_absolute,
                    error.relative_rms(), worst_channel[i], error.finite ? 1 : 0,
                    std::sqrt(error.reference_squared / reference.size()));
    }
    engines.clear();
    for (auto* factory : factories) deleteDSPFactory(factory);
}
