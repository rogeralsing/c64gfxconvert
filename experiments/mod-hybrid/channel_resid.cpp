// Narrow C ABI around the unmodified reSID core distributed with VICE3.10.
// The linked core is GPL-2.0-or-later; its source and COPYING accompany it.
#include "sid.h"
#include <cmath>
#include <exception>

static void* create_sid(double rate, double clock, double bias_mv, bool digiboost) {
    try {
        auto* sid = new reSID::SID();
        sid->set_chip_model(digiboost ? reSID::MOS8580 : reSID::MOS6581);
        sid->set_voice_mask(digiboost ? 0x0f : 0x07);
        sid->input(digiboost ? -32768 : 0);
        sid->enable_filter(true);
        sid->enable_external_filter(true);
        sid->adjust_filter_bias(bias_mv / 1000.0);
        if (!sid->set_sampling_parameters(clock, reSID::SAMPLE_RESAMPLE,
                                          rate, rate * 0.45, 0.97)) {
            delete sid;
            return nullptr;
        }
        return sid;
    } catch (...) { return nullptr; }
}

extern "C" {
void* c64_resid_create(double rate, double clock, double bias_mv) {
    return create_sid(rate, clock, bias_mv, false);
}

void* c64_resid_create_digiboost(double rate, double clock, double bias_mv) {
    return create_sid(rate, clock, bias_mv, true);
}

void c64_resid_destroy(void* handle) {
    delete static_cast<reSID::SID*>(handle);
}

void c64_resid_write(void* handle, unsigned int reg, unsigned int value) {
    static_cast<reSID::SID*>(handle)->write(reg, value);
}

int c64_resid_clock(void* handle, int cycles, short* output, int capacity) {
    try {
        int remaining = cycles;
        int count = static_cast<reSID::SID*>(handle)->clock(remaining, output, capacity, 1);
        return remaining ? -1 : count;
    } catch (...) { return -2; }
}
}
