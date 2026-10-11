// Shift a hidden LED-matrix frame sideways.
//
// Rewriting every pixel calls into the matrix library once per LED. On this
// panel that is 384x32 scattered bit-plane writes, which stalls the refresh
// thread and makes the picture pulse brighter and darker while scrolling.
// Adjacent columns are adjacent words in the off-screen frame, so a scroll
// can move those words and redraw only the columns that entered the screen.

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <cstring>

#include "led-matrix.h"
#include "framebuffer-internal.h"

namespace {

struct PyCanvasHead {
    PyObject_HEAD
    void *vtab;
    void *canvas;
};

static_assert(
    sizeof(PyCanvasHead) == 32,
    "FrameCanvas wrapper layout does not match this Python build");

rgb_matrix::internal::Framebuffer *buffer_of(PyObject *object) {
    if (object == nullptr || Py_TYPE(object)->tp_basicsize < static_cast<Py_ssize_t>(sizeof(PyCanvasHead))) {
        return nullptr;
    }

    const char *name = Py_TYPE(object)->tp_name;
    if (name == nullptr || std::strcmp(name, "rgbmatrix.core.FrameCanvas") != 0) {
        return nullptr;
    }

    auto *canvas = reinterpret_cast<PyCanvasHead *>(object)->canvas;
    if (canvas == nullptr) {
        return nullptr;
    }

    // FrameCanvas stores its framebuffer at byte 8. Confirmed from
    // FrameCanvas::width() in the installed librgbmatrix.
    auto **slot = reinterpret_cast<rgb_matrix::internal::Framebuffer **>(
        reinterpret_cast<char *>(canvas) + sizeof(void *));
    rgb_matrix::internal::Framebuffer *buffer = *slot;
    if (buffer == nullptr) {
        return nullptr;
    }

    const int columns = buffer->columns();
    const int rows = buffer->double_rows();
    if (columns < 8 || columns > 4096 || rows < 4 || rows > 128) {
        return nullptr;
    }
    return buffer;
}

bool shift_buffer(rgb_matrix::internal::Framebuffer *buffer, int amount) {
    const int columns = buffer->columns();
    if (amount <= 0 || amount >= columns) {
        return false;
    }

    const int rows = buffer->double_rows();
    const size_t kept = static_cast<size_t>(columns - amount) * sizeof(gpio_bits_t);
    for (int row = 0; row < rows; ++row) {
        for (int bit = 0; bit < rgb_matrix::internal::Framebuffer::kBitPlanes; ++bit) {
            gpio_bits_t *words = const_cast<gpio_bits_t *>(buffer->RowDataAt(row, bit));
            std::memmove(words, words + amount, kept);
        }
    }
    return true;
}

PyObject *py_scroll_columns(PyObject *, PyObject *args) {
    PyObject *canvas_obj = nullptr;
    PyObject *rgb_obj = nullptr;
    int amount = 0;
    int period = 0;
    int height = 0;
    int origin = 0;
    int view_width = 0;
    if (!PyArg_ParseTuple(
            args,
            "OiOiiii",
            &canvas_obj,
            &amount,
            &rgb_obj,
            &period,
            &height,
            &origin,
            &view_width)) {
        return nullptr;
    }

    auto *buffer = buffer_of(canvas_obj);
    if (buffer == nullptr) {
        Py_RETURN_FALSE;
    }
    auto *frame = reinterpret_cast<rgb_matrix::FrameCanvas *>(
        reinterpret_cast<PyCanvasHead *>(canvas_obj)->canvas);
    if (
        frame == nullptr
        || view_width != buffer->columns()
        || period <= 0
        || height <= 0
        || amount <= 0
        || amount >= view_width
    ) {
        Py_RETURN_FALSE;
    }

    Py_buffer view;
    if (PyObject_GetBuffer(rgb_obj, &view, PyBUF_SIMPLE) != 0) {
        return nullptr;
    }

    const Py_ssize_t needed = static_cast<Py_ssize_t>(period) * height * 3;
    if (view.len < needed || view.buf == nullptr) {
        PyBuffer_Release(&view);
        Py_RETURN_FALSE;
    }

    if (!shift_buffer(buffer, amount)) {
        PyBuffer_Release(&view);
        Py_RETURN_FALSE;
    }

    const auto *rgb = static_cast<const uint8_t *>(view.buf);
    int start = origin % period;
    if (start < 0) {
        start += period;
    }
    start = (start + view_width - amount) % period;

    for (int col = 0; col < amount; ++col) {
        const int src_x = (start + col) % period;
        const int dest_x = view_width - amount + col;
        for (int y = 0; y < height; ++y) {
            const uint8_t *pixel = rgb + (static_cast<size_t>(y) * period + src_x) * 3;
            frame->SetPixel(dest_x, y, pixel[0], pixel[1], pixel[2]);
        }
    }

    PyBuffer_Release(&view);
    Py_RETURN_TRUE;
}

PyObject *py_canvas_key(PyObject *, PyObject *args) {
    PyObject *canvas = nullptr;
    if (!PyArg_ParseTuple(args, "O", &canvas)) {
        return nullptr;
    }

    auto *native = reinterpret_cast<PyCanvasHead *>(canvas);
    if (buffer_of(canvas) == nullptr || native->canvas == nullptr) {
        Py_RETURN_NONE;
    }
    return PyLong_FromVoidPtr(native->canvas);
}

PyObject *py_shift_left(PyObject *, PyObject *args) {
    PyObject *canvas = nullptr;
    int amount = 0;
    if (!PyArg_ParseTuple(args, "Oi", &canvas, &amount)) {
        return nullptr;
    }

    auto *buffer = buffer_of(canvas);
    if (buffer == nullptr || !shift_buffer(buffer, amount)) {
        Py_RETURN_FALSE;
    }
    Py_RETURN_TRUE;
}

PyObject *py_capture_buffer(PyObject *, PyObject *args) {
    PyObject *canvas = nullptr;
    if (!PyArg_ParseTuple(args, "O", &canvas)) {
        return nullptr;
    }

    auto *buffer = buffer_of(canvas);
    if (buffer == nullptr) {
        Py_RETURN_NONE;
    }

    const size_t words = static_cast<size_t>(buffer->double_rows())
        * static_cast<size_t>(buffer->columns())
        * static_cast<size_t>(rgb_matrix::internal::Framebuffer::kBitPlanes);
    const size_t bytes = words * sizeof(gpio_bits_t);
    gpio_bits_t *start = const_cast<gpio_bits_t *>(buffer->RowDataAt(0, 0));
    return PyBytes_FromStringAndSize(reinterpret_cast<const char *>(start), static_cast<Py_ssize_t>(bytes));
}

PyMethodDef methods[] = {
    {"canvas_key", py_canvas_key, METH_VARARGS, "Stable id for an off-screen frame."},
    {"shift_left", py_shift_left, METH_VARARGS, "Move an off-screen frame left by whole columns."},
    {"scroll_columns", py_scroll_columns, METH_VARARGS, "Shift the hidden frame and draw the columns that entered."},
    {"capture_buffer", py_capture_buffer, METH_VARARGS, "Copy the off-screen bit planes."},
    {nullptr, nullptr, 0, nullptr},
};

PyModuleDef module_def = {
    PyModuleDef_HEAD_INIT,
    "panel_shift",
    "Fast horizontal shifts for the LED matrix back buffer.",
    -1,
    methods,
};

}  // namespace

PyMODINIT_FUNC PyInit_panel_shift(void) {
    return PyModule_Create(&module_def);
}
