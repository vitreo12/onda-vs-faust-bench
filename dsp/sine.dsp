import("stdfaust.lib");

freq = hslider("freq[scale:log]", 440.0, 20.0, 10000.0, 0.01);
level = hslider("level", 0.6, 0.0, 1.0, 0.01);
twoPi = 2.0 * ma.PI;
increment = freq * twoPi / ma.SR;

wrap(x) = x - select2(x > twoPi, 0.0, twoPi);
phase = (+(increment) : wrap) ~ _;
process = phase' : sin : *(level);
