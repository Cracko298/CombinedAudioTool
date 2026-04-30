#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

static int clamp16_ll(long long v) {
    if (v > 32767) return 32767;
    if (v < -32768) return -32768;
    return (int)v;
}

static int16_t read_le_i16(const unsigned char *p) {
    uint16_t u = (uint16_t)p[0] | ((uint16_t)p[1] << 8);
    return (int16_t)u;
}

static void write_le_i16(unsigned char *p, int v) {
    int16_t s = (int16_t)v;
    uint16_t u = (uint16_t)s;
    p[0] = (unsigned char)(u & 0xFF);
    p[1] = (unsigned char)((u >> 8) & 0xFF);
}

static int signed_nibble(int n) {
    return (n & 0x8) ? (n - 16) : n;
}

static int decode_dsp_sample_c(int nibble, int scale_shift, int coef1, int coef2, int hist1, int hist2) {
    long long scale = 1LL << scale_shift;
    long long v = ((((long long)nibble * scale) << 11) + 1024 + ((long long)coef1 * hist1) + ((long long)coef2 * hist2)) >> 11;
    return clamp16_ll(v);
}

static int sample_to_nibble_address(int sample_index) {
    int frame = sample_index / 14;
    int in_frame = sample_index % 14;
    return frame * 16 + 2 + in_frame;
}

static int samples_to_nibbles(int sample_count) {
    int frames = (sample_count + 13) / 14;
    return frames * 16;
}

static int parse_coeff_pairs(PyObject *seq, int coefs[8][2]) {
    PyObject *fast = PySequence_Fast(seq, "coefs must be a sequence of 8 (coef1, coef2) pairs");
    if (!fast) return 0;
    Py_ssize_t n = PySequence_Fast_GET_SIZE(fast);
    if (n < 8) {
        Py_DECREF(fast);
        PyErr_SetString(PyExc_ValueError, "coefs must contain at least 8 pairs");
        return 0;
    }
    PyObject **items = PySequence_Fast_ITEMS(fast);
    for (int i = 0; i < 8; i++) {
        PyObject *pair_fast = PySequence_Fast(items[i], "each coef pair must be a sequence");
        if (!pair_fast) {
            Py_DECREF(fast);
            return 0;
        }
        if (PySequence_Fast_GET_SIZE(pair_fast) < 2) {
            Py_DECREF(pair_fast);
            Py_DECREF(fast);
            PyErr_SetString(PyExc_ValueError, "each coef pair must contain two integers");
            return 0;
        }
        PyObject **pitems = PySequence_Fast_ITEMS(pair_fast);
        long c1 = PyLong_AsLong(pitems[0]);
        long c2 = PyLong_AsLong(pitems[1]);
        Py_DECREF(pair_fast);
        if (PyErr_Occurred()) {
            Py_DECREF(fast);
            return 0;
        }
        if (c1 < -32768) c1 = -32768;
        if (c1 > 32767) c1 = 32767;
        if (c2 < -32768) c2 = -32768;
        if (c2 > 32767) c2 = 32767;
        coefs[i][0] = (int)c1;
        coefs[i][1] = (int)c2;
    }
    Py_DECREF(fast);
    return 1;
}

static PyObject *catool_fast_decode_channel(PyObject *self, PyObject *args) {
    const unsigned char *payload = NULL;
    Py_ssize_t payload_len = 0;
    int sample_count = 0;
    PyObject *coef_obj = NULL;
    int hist1 = 0, hist2 = 0;

    if (!PyArg_ParseTuple(args, "y#iO|ii:decode_channel", &payload, &payload_len, &sample_count, &coef_obj, &hist1, &hist2)) {
        return NULL;
    }
    if (sample_count < 0) {
        PyErr_SetString(PyExc_ValueError, "sample_count cannot be negative");
        return NULL;
    }
    int coefs[8][2];
    if (!parse_coeff_pairs(coef_obj, coefs)) return NULL;

    PyObject *out = PyBytes_FromStringAndSize(NULL, (Py_ssize_t)sample_count * 2);
    if (!out) return NULL;
    unsigned char *dst = (unsigned char *)PyBytes_AS_STRING(out);
    int out_index = 0;
    Py_ssize_t pos = 0;

    while (out_index < sample_count && pos + 8 <= payload_len) {
        unsigned char header = payload[pos++];
        int pred_idx = (header >> 4) & 0x0F;
        int scale_shift = header & 0x0F;
        if (pred_idx >= 8) pred_idx = 0;
        int coef1 = coefs[pred_idx][0];
        int coef2 = coefs[pred_idx][1];
        for (int byte_i = 0; byte_i < 7 && out_index < sample_count; byte_i++) {
            unsigned char b = payload[pos++];
            int n1 = signed_nibble((b >> 4) & 0x0F);
            int sample = decode_dsp_sample_c(n1, scale_shift, coef1, coef2, hist1, hist2);
            write_le_i16(dst + (out_index * 2), sample);
            hist2 = hist1;
            hist1 = sample;
            out_index++;
            if (out_index >= sample_count) break;
            int n2 = signed_nibble(b & 0x0F);
            sample = decode_dsp_sample_c(n2, scale_shift, coef1, coef2, hist1, hist2);
            write_le_i16(dst + (out_index * 2), sample);
            hist2 = hist1;
            hist1 = sample;
            out_index++;
        }
    }
    while (out_index < sample_count) {
        write_le_i16(dst + (out_index * 2), 0);
        out_index++;
    }
    return out;
}

static int quantize_residual(int residual, int shift) {
    int scale = 1 << shift;
    int q;
    if (residual >= 0) q = (residual + (scale / 2)) / scale;
    else q = -((-residual + (scale / 2)) / scale);
    if (q < -8) q = -8;
    if (q > 7) q = 7;
    return q;
}

static void choose_best_frame(const int16_t *pcm, int frame_len, int coefs[8][2], int hist1, int hist2,
                              int *best_pred, int *best_shift, unsigned char best_nibbles[14], int *best_hist1, int *best_hist2) {
    long long best_error = -1;
    int chosen_pred = 0, chosen_shift = 0, chosen_h1 = hist1, chosen_h2 = hist2;
    unsigned char chosen_nibbles[14];
    memset(chosen_nibbles, 0, sizeof(chosen_nibbles));

    for (int pred = 0; pred < 8; pred++) {
        int coef1 = coefs[pred][0];
        int coef2 = coefs[pred][1];
        int th1 = hist1, th2 = hist2;
        int max_residual = 0;
        for (int i = 0; i < frame_len; i++) {
            int predicted = (int)(((long long)coef1 * th1 + (long long)coef2 * th2 + 1024) >> 11);
            int residual = (int)pcm[i] - predicted;
            int ar = residual < 0 ? -residual : residual;
            if (ar > max_residual) max_residual = ar;
            th2 = th1;
            th1 = (int)pcm[i];
        }

        int scale_shift = 0;
        while (scale_shift < 12 && max_residual > (7 << scale_shift)) scale_shift++;
        int deltas[4] = {-1, 0, 1, 2};
        int used[13];
        memset(used, 0, sizeof(used));
        for (int di = 0; di < 4; di++) {
            int ss = scale_shift + deltas[di];
            if (ss < 0) ss = 0;
            if (ss > 12) ss = 12;
            if (used[ss]) continue;
            used[ss] = 1;

            int cur_h1 = hist1, cur_h2 = hist2;
            unsigned char nibbles[14];
            memset(nibbles, 0, sizeof(nibbles));
            long long total_error = 0;
            for (int i = 0; i < frame_len; i++) {
                int predicted = (int)(((long long)coef1 * cur_h1 + (long long)coef2 * cur_h2 + 1024) >> 11);
                int residual = (int)pcm[i] - predicted;
                int q = quantize_residual(residual, ss);
                int decoded = decode_dsp_sample_c(q, ss, coef1, coef2, cur_h1, cur_h2);
                int err = (int)pcm[i] - decoded;
                total_error += (long long)err * (long long)err;
                cur_h2 = cur_h1;
                cur_h1 = decoded;
                nibbles[i] = (unsigned char)(q & 0x0F);
            }
            if (best_error < 0 || total_error < best_error) {
                best_error = total_error;
                chosen_pred = pred;
                chosen_shift = ss;
                chosen_h1 = cur_h1;
                chosen_h2 = cur_h2;
                memcpy(chosen_nibbles, nibbles, sizeof(chosen_nibbles));
            }
        }
    }

    *best_pred = chosen_pred;
    *best_shift = chosen_shift;
    *best_hist1 = chosen_h1;
    *best_hist2 = chosen_h2;
    memcpy(best_nibbles, chosen_nibbles, 14);
}

static PyObject *catool_fast_encode_channel(PyObject *self, PyObject *args) {
    const unsigned char *pcm_bytes = NULL;
    Py_ssize_t pcm_len = 0;
    PyObject *coef_obj = NULL;
    int loop_start = -1, loop_end = -1;

    if (!PyArg_ParseTuple(args, "y#O|ii:encode_channel", &pcm_bytes, &pcm_len, &coef_obj, &loop_start, &loop_end)) {
        return NULL;
    }
    if (pcm_len % 2 != 0) {
        PyErr_SetString(PyExc_ValueError, "PCM byte data must be 16-bit little-endian samples");
        return NULL;
    }
    int coefs[8][2];
    if (!parse_coeff_pairs(coef_obj, coefs)) return NULL;

    int sample_count = (int)(pcm_len / 2);
    int loop_flag = 0;
    int loop_start_nibble = 0;
    int loop_end_nibble = sample_count > 0 ? sample_to_nibble_address(sample_count - 1) : 0;
    if (loop_start >= 0 || loop_end >= 0) {
        if (!(0 <= loop_start && loop_start < loop_end && loop_end <= sample_count)) {
            PyErr_SetString(PyExc_ValueError, "Invalid DSP loop points");
            return NULL;
        }
        loop_flag = 1;
        loop_start_nibble = sample_to_nibble_address(loop_start);
        loop_end_nibble = sample_to_nibble_address(loop_end - 1);
    }

    int frame_count = (sample_count + 13) / 14;
    PyObject *adpcm = PyBytes_FromStringAndSize(NULL, (Py_ssize_t)frame_count * 8);
    if (!adpcm) return NULL;
    unsigned char *out = (unsigned char *)PyBytes_AS_STRING(adpcm);

    int hist1 = 0, hist2 = 0;
    int initial_ps = 0, initial_hist1 = 0, initial_hist2 = 0;
    int loop_ps = 0, loop_hist1 = 0, loop_hist2 = 0;
    int loop_frame_index = loop_flag ? (loop_start / 14) : -1;

    for (int frame = 0; frame < frame_count; frame++) {
        int start = frame * 14;
        int frame_len = sample_count - start;
        if (frame_len > 14) frame_len = 14;
        int16_t block[14];
        memset(block, 0, sizeof(block));
        for (int i = 0; i < frame_len; i++) {
            block[i] = read_le_i16(pcm_bytes + ((start + i) * 2));
        }

        int pred = 0, shift = 0, new_h1 = hist1, new_h2 = hist2;
        unsigned char nibbles[14];
        choose_best_frame(block, frame_len, coefs, hist1, hist2, &pred, &shift, nibbles, &new_h1, &new_h2);
        int ps = ((pred & 0x0F) << 4) | (shift & 0x0F);
        if (frame == 0) {
            initial_ps = ps;
            initial_hist1 = hist1;
            initial_hist2 = hist2;
        }
        if (loop_flag && frame == loop_frame_index) {
            loop_ps = ps;
            loop_hist1 = hist1;
            loop_hist2 = hist2;
        }
        unsigned char *dst = out + (frame * 8);
        dst[0] = (unsigned char)ps;
        for (int i = 0; i < 14; i += 2) {
            dst[1 + (i / 2)] = (unsigned char)(((nibbles[i] & 0x0F) << 4) | (nibbles[i + 1] & 0x0F));
        }
        hist1 = new_h1;
        hist2 = new_h2;
    }

    PyObject *dict = PyDict_New();
    if (!dict) {
        Py_DECREF(adpcm);
        return NULL;
    }
#define SET_INT(name, value) do { PyObject *v = PyLong_FromLong((long)(value)); if (!v) { Py_DECREF(adpcm); Py_DECREF(dict); return NULL; } PyDict_SetItemString(dict, (name), v); Py_DECREF(v); } while (0)
    SET_INT("sample_count", sample_count);
    SET_INT("nibble_count", samples_to_nibbles(sample_count));
    SET_INT("loop_flag", loop_flag);
    SET_INT("loop_start_nibble", loop_start_nibble);
    SET_INT("loop_end_nibble", loop_end_nibble);
    SET_INT("current_address", 0);
    SET_INT("initial_ps", initial_ps);
    SET_INT("initial_hist1", initial_hist1);
    SET_INT("initial_hist2", initial_hist2);
    SET_INT("loop_ps", loop_flag ? loop_ps : 0);
    SET_INT("loop_hist1", loop_flag ? loop_hist1 : 0);
    SET_INT("loop_hist2", loop_flag ? loop_hist2 : 0);
#undef SET_INT
    PyDict_SetItemString(dict, "adpcm_bytes", adpcm);
    Py_DECREF(adpcm);
    return dict;
}

static PyMethodDef CatoolFastMethods[] = {
    {"decode_channel", catool_fast_decode_channel, METH_VARARGS, "Decode one Nintendo DSP/GCADPCM channel to little-endian PCM16 bytes."},
    {"encode_channel", catool_fast_encode_channel, METH_VARARGS, "Encode one little-endian PCM16 channel to Nintendo DSP/GCADPCM ADPCM bytes."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef CatoolFastModule = {
    PyModuleDef_HEAD_INIT,
    "catool_fast",
    "Fast CPython helpers for CATool DSP/GCADPCM encode/decode.",
    -1,
    CatoolFastMethods
};

PyMODINIT_FUNC PyInit_catool_fast(void) {
    return PyModule_Create(&CatoolFastModule);
}
