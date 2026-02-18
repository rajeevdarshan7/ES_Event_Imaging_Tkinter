import tkinter as tk
from tkinter import ttk
import serial
import threading
import math

# ---------- CONFIG ----------
PORT = "COM3"       # Change for your system, e.g. "/dev/ttyUSB0"
BAUD = 115200
NUM_VALUES = 900     # Can be changed (e.g. 100 → 10×10 grid, 36 → 6×6 grid)
GRID_SIZE = int(math.sqrt(NUM_VALUES))
# ----------------------------

ser = None
running = False

def read_serial():
    global running
    while running:
        try:
            line = ser.readline().decode('utf-8').strip()
            if not line:
                continue
            values = [float(x) for x in line.split()]
            if len(values) == NUM_VALUES:
                update_grid(values)
        except Exception:
            continue  # ignore parsing/serial errors if port closed

def start_scan():
    global ser, running
    if running:
        return
    try:
        ser = serial.Serial(PORT, BAUD, timeout=1)
        message = "start"
        ser.write(message.encode())
    except Exception as e:
        print("Serial error:", e)
        return

    running = True
    thread = threading.Thread(target=read_serial, daemon=True)
    thread.start()

def stop_scan():
    global running, ser
    running = False
    if ser:
        try:
            ser.close()
        except:
            pass
        ser = None

def value_to_color(value, vmin, vmax):
    """ Map a value to a RGB heatmap color (blue → green → yellow → red). """
    if vmax == vmin:
        return "#000000"
    ratio = (value - vmin) / (vmax - vmin)
    ratio = max(0.0, min(1.0, ratio))  # clamp to [0,1]

    r = 255 * ratio
    g = 0
    b = 120 * ratio

    return f"#{r:02x}{g:02x}{b:02x}"

def update_grid(values):
    vmin = 0
    vmax = 5
    sorted_vals = values
    for i, val in enumerate(sorted_vals):
        color = value_to_color(val, vmin, vmax)
        canvas.itemconfig(rects[i], fill=color)

# ---------- Tkinter GUI ----------
root = tk.Tk()
root.title("900-Point Scan Viewer")

frame = ttk.Frame(root)
frame.pack(pady=10)

btn_start = ttk.Button(frame, text="Start Scan", command=start_scan)
btn_start.grid(row=0, column=0, padx=5)

btn_stop = ttk.Button(frame, text="Stop Scan", command=stop_scan)
btn_stop.grid(row=0, column=1, padx=5)

canvas = tk.Canvas(root, width=400, height=400)
canvas.pack(pady=10)

rects = []
cell_size = 400 // GRID_SIZE

for y in range(GRID_SIZE):
    for x in range(GRID_SIZE):
        rect = canvas.create_rectangle(
            x*cell_size, y*cell_size,
            (x+1)*cell_size, (y+1)*cell_size,
            outline="black", fill="white"
        )
        rects.append(rect)

root.protocol("WM_DELETE_WINDOW", lambda: (stop_scan(), root.destroy()))
root.mainloop()
