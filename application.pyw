import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import numpy as np
import serial
import serial.tools.list_ports
from threading import Thread, Event
import queue
import time
import os

DEFAULT_SENSOR = "ES Sensor 8x8"

SENSOR_PROFILES = {
    "X-Sensor 4x4": (4, 4),  # Additional Sensor
    "ES Sensor 1x1": (1, 1),
    "ES Sensor 2x2": (2, 2),
    "ES Sensor 3x3": (3, 3),
    "ES Sensor 4x4": (4, 4),
    "ES Sensor 6x6": (6, 6),
    "ES Sensor 7x7": (7, 7),
    "ES Sensor 8x8": (8, 8),
    "ES Sensor 9x9": (9, 9),
    "ES Sensor 10x10": (10,10)
}

# Set CustomTkinter appearance
ctk.set_appearance_mode("System")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
THEME_PATH = os.path.join(BASE_DIR, "themes", "metal.json")
ctk.set_default_color_theme(THEME_PATH)

class App(ctk.CTk):
    def __init__(self, update_interval=250):
        super().__init__()
        # self.overrideredirect(True) # removes default windows title bar
        # self.bind("<Map>", self.recover_window)

        # Initialize
        rows, cols = SENSOR_PROFILES[DEFAULT_SENSOR]
        self.sensor_rows = rows
        self.sensor_cols = cols
        self.data = np.random.rand(rows, cols)
        self.mode = "Normal"
        self.gain = 1 # to be passed into port
        self.offset = np.zeros(self.data.shape)
        self.initFlag = True
        self.recording = False
        self.tmp_gif = []
        self.update_interval = update_interval
        self.title("Electrostatic Event Imaging Sensor")
        self.serial_port = None
        self.serial_thread = None
        self.serial_event = Event()
        self.data_queue = queue.Queue()
        self.debug = False
        self.cbar = None
        self.acq_mode = "VIDEO"
        self.snapshot_pending = False
        self.scan_active = False
        self.scan_x_step = 0
        self.scan_y_step = 0
        self.scan_x_steps = 1
        self.scan_y_steps = 1
        self.scan_buffer = None

        # Set minimum width and height for App
        minwidth = 835
        minheight = 500
        self.minsize(minwidth, minheight)
        
        # Configure grid layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Create main container frame
        self.main_frame = ctk.CTkFrame(self, corner_radius=0)
        self.main_frame.grid(row=0, column=0)
        self.main_frame.grid_columnconfigure(1, weight=2, minsize=290)
        self.main_frame.grid_rowconfigure(1, weight=1)

        # Create plot frame (left side)
        self.plot_frame = ctk.CTkFrame(master=self.main_frame)
        self.plot_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        
        # Create control frame (right side)
        self.control_frame = ctk.CTkScrollableFrame(master=self.main_frame)
        self.control_frame.grid(row=0, column=1, padx=(2.5,2.5), pady=10, sticky="nsew")
        self.control_frame.grid_columnconfigure(1, weight=1)
        self.control_frame.grid_rowconfigure(3, weight=1)

        # Create serial frame (right upper side)
        self.serial_frame = ctk.CTkFrame(master=self.control_frame)
        self.serial_frame.grid(row=0, column=0, padx=(2.5,10), pady=10, sticky="e")

        # Create panel frame (right mid side)
        self.panel_frame = ctk.CTkFrame(master=self.control_frame)
        self.panel_frame.grid(row=1, column=0, padx=(2.5,10), pady=10, sticky="e")

        # Create terminal frame (right bottom side)
        self.dev_frame = ctk.CTkFrame(master=self.control_frame)

        # Drag Button
        drag_button = ctk.CTkButton(self, text="≡", font=("Arial", 20, "bold"), width=40) 
        # Bind mouse events to the button
        drag_button.bind("<ButtonPress-1>", self.start_drag)
        drag_button.bind("<B1-Motion>", self.move_window)
        drag_button.bind("<ButtonRelease-1>", self.stop_drag)
        drag_button.place(x = 6, y = 30) 

        # Close Application Button
        # exit_button = ctk.CTkButton(self, text="X", font=("Arial", 20, "bold"), fg_color="#d13b30", width=40, command=self.destroy) 
        # exit_button.place(x = 6, y = 70) 

        # Minimize Button
        minimize_button = ctk.CTkButton(self, text = "⬋", font=("Arial", 20, "bold"), fg_color="#db9730", width=40, command = self.minimize_window)
        minimize_button.place(x = 6, y = 110) 

        # Debug Button
        self.debug_button = ctk.CTkButton(self, text = "Dev", font=("Arial", 20, "bold"), fg_color="#dd3b30", width=40, command = self.toggle_terminal)
        self.debug_button.place(x = 6, y = 150) 

        self.snapshot_button = ctk.CTkButton(
            self.panel_frame,
            text="📸 Capture Snapshot",
            command=self.capture_snapshot
        )

        # Initially hidden (VIDEO mode)
        self.snapshot_button.grid(row=11, column=0, pady=(10, 10))
        self.snapshot_button.grid_remove()

        # Initialize plot
        self.setup_plot()
        self.setup_controls()
        
        # Initialize update flag
        self.update_interval = update_interval
        self.updating = False

        # Initiliaze UI 
        self.ui_state = "IDLE"
        self.update_controls_ui()

        # check for serial
        self.after(20, self.process_serial_data)

    def setup_plot(self):
        self.fig = Figure(figsize=(7, 6), dpi=100)
        self.ax = self.fig.add_subplot(111)

        # Initial data
        self.img = self.ax.imshow(
            self.data,
            interpolation="nearest",
            cmap="plasma",
            aspect="equal",
            vmin=0,
            vmax=5
        )

        # ---- FIXED COLORBAR AXIS ----
        divider = make_axes_locatable(self.ax)
        self.cax = divider.append_axes("right", size="5%", pad=0.1)

        self.cbar = self.fig.colorbar(self.img, cax=self.cax)

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.plot_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=12, pady=12)

    def setup_serial_controls(self):
        # Serial port controls
        self.serial_header = ctk.CTkLabel(self.serial_frame, text="Serial Port Controls", font=("Arial", 20, "bold"))
        self.serial_header.pack(pady=(10, 5))

        # COM Port selection
        self.com_frame = ctk.CTkFrame(self.serial_frame)
        self.com_frame.pack(expand=True, padx=10, pady=5)

        self.refresh_btn = ctk.CTkButton(self.com_frame, font=("Arial", 20, "bold"), text="↻", width=30, command=self.refresh_ports)
        self.refresh_btn.pack(side="right", padx=5, pady=5)
        
        self.port_label = ctk.CTkLabel(self.com_frame, text="Port:")
        self.port_label.pack(side="left", padx=5, pady=5)
        
        self.port_option = ctk.CTkComboBox(self.com_frame, values=self.get_available_ports())
        self.port_option.pack(side="left", padx=5, pady=5)

        # Baud rate selection
        self.baud_label = ctk.CTkLabel(self.serial_frame, text="Baud Rate:")
        self.baud_label.pack(pady=(5, 0))
        
        self.baud_option = ctk.CTkComboBox(self.serial_frame, 
                                         values=["115200", "57600", "38400", "19200", "9600", "4800"])
        self.baud_option.pack(fill="x", padx=10, pady=5)
        self.baud_option.set("9600")

        # Connection controls
        self.connect_btn = ctk.CTkButton(self.serial_frame, 
                                       text="Open Port", 
                                       command=self.toggle_serial_connection)
        self.connect_btn.pack(pady=10)

    # May not be needed, can be added for dev mode but not neccessary
    def setup_terminal(self):
        # Terminal display
        self.terminal_label = ctk.CTkLabel(self.dev_frame, text="Serial Terminal", font=("Arial", 20, "bold"))
        self.terminal_label.pack(pady=(10, 5))
        
        self.terminal = ctk.CTkTextbox(self.dev_frame, height=200)
        self.terminal.pack(fill="x", padx=5, pady=5)
        
        # Send controls
        self.send_frame = ctk.CTkFrame(self.dev_frame)
        self.send_frame.pack(fill="x", padx=5, pady=5)
        
        self.entry = ctk.CTkEntry(self.send_frame, placeholder_text="Enter message")
        self.entry.pack(side="left", fill="x", expand=True, padx=5, pady=5)
        # self.entry.bind("<Return>", lambda e: self.send_serial_message())
        
        self.send_btn = ctk.CTkButton(self.send_frame, text="Send", width=60, command=self.send_serial_message)
        self.send_btn.pack(side="left", padx=5, pady=5)

        # Clear button
        self.clear_btn = ctk.CTkButton(self.dev_frame, text="Clear Terminal", command=self.clear_terminal)
        self.clear_btn.pack(padx=5, pady=(5, 10))

    def setup_controls(self):
        ACTION_ROW = 13

        # -----------------------------
        # Serial Port Controls
        # -----------------------------
        self.setup_serial_controls()

        # -----------------------------
        # Controls Title
        # -----------------------------
        self.title_label = ctk.CTkLabel(
            self.panel_frame,
            text="Controls",
            font=("Arial", 20, "bold")
        )
        self.title_label.grid(row=0, column=0, pady=(10, 5))

        # -----------------------------
        # Humidity Display
        # -----------------------------
        self.humidity_label = ctk.CTkLabel(
            self.panel_frame,
            text="Humidity: -- %",
            font=("Arial", 16, "bold"),
            text_color="#7CFC98"
        )

        self.humidity_label.grid(
            row=ACTION_ROW + 6,
            column=0,
            pady=(5, 10)
)

        # =============================
        # CONFIGURATION SECTION
        # =============================

        # ---- Mode Selection ----
        self.mode_label = ctk.CTkLabel(self.panel_frame, text="Mode Selection:")
        self.mode_label.grid(row=1, column=0, pady=(5, 2))

        self.mode_select = ctk.CTkOptionMenu(
            self.panel_frame,
            values=["Normal", "Color", "Threshold"],
            command=self.update_mode
        )
        self.mode_select.grid(row=2, column=0, pady=(0, 8))
        self.mode_select.set("Normal")

        # ---- Refresh Speed ----
        self.speed_frame = ctk.CTkFrame(self.panel_frame)
        self.speed_frame.grid(row=3, column=0, padx=10, pady=5, sticky="ew")
        self.speed_frame.grid_columnconfigure(1, weight=1)

        self.speed_label = ctk.CTkLabel(self.speed_frame, text="Refresh Speed:")
        self.speed_label.grid(row=0, column=0, sticky="w", padx=5)

        self.speed_value_slider = ctk.CTkLabel(
            self.speed_frame,
            text=f"{self.update_interval}ms"
        )
        self.speed_value_slider.grid(row=0, column=1, sticky="e", padx=5)

        self.speed_slider = ctk.CTkSlider(
            self.speed_frame,
            from_=2000,
            to=250,
            number_of_steps=50,
            command=self.update_speed
        )
        self.speed_slider.grid(
            row=1, column=0, columnspan=2,
            sticky="ew", padx=5, pady=8
        )
        self.speed_slider.set(self.update_interval)

        # ---- Sensor Type ----
        self.sensor_label = ctk.CTkLabel(self.panel_frame, text="Sensor Type:")
        self.sensor_label.grid(row=4, column=0, pady=(10, 2))

        self.sensor_select = ctk.CTkOptionMenu(
            self.panel_frame,
            values=list(SENSOR_PROFILES.keys()),
            command=self.change_sensor
        )
        self.sensor_select.grid(row=5, column=0, pady=(0, 8))
        self.sensor_select.set("ES Sensor 8x8")

        # ---- Acquisition Mode ----
        self.acq_label = ctk.CTkLabel(self.panel_frame, text="Acquisition Mode:")
        self.acq_label.grid(row=6, column=0, pady=(10, 2))

        self.acq_select = ctk.CTkOptionMenu(
            self.panel_frame,
            values=["VIDEO", "SNAPSHOT"],
            command=self.change_acq_mode
        )
        self.acq_select.grid(row=7, column=0, pady=(0, 8))
        self.acq_select.set("VIDEO")

        # ---- Scan / Interleaving ----
        self.scan_label = ctk.CTkLabel(
            self.panel_frame,
            text="X / Y Interleaving Steps:"
        )
        self.scan_label.grid(row=8, column=0, pady=(10, 2))

        self.scan_entry_x = ctk.CTkEntry(self.panel_frame, width=80)
        self.scan_entry_x.insert(0, "1")
        self.scan_entry_x.grid(row=9, column=0, pady=(0, 4))

        self.scan_entry_y = ctk.CTkEntry(self.panel_frame, width=80)
        self.scan_entry_y.insert(0, "1")
        self.scan_entry_y.grid(row=10, column=0, pady=(0, 6))

        self.scan_start_btn = ctk.CTkButton(
            self.panel_frame,
            text="Start Scan",
            command=self.start_scan
        )
        self.scan_start_btn.grid(row=11, column=0, pady=(0, 10))

        self.scan_next_btn = ctk.CTkButton(
            self.panel_frame,
            text="Next",
            command=self.scan_next
        )
        self.scan_next_btn.grid(row=12, column=0, pady=(0, 10))
        self.scan_next_btn.grid_remove()

        # =============================
        # ACTION BUTTON ZONE (FIXED)
        # =============================
        ACTION_ROW = 13

        self.capture_button = ctk.CTkButton(
            self.panel_frame,
            text="Capture",
            command=self.capture
        )
        self.capture_button.grid(row=ACTION_ROW, column=0, pady=5)
        self.capture_button.grid_remove()

        self.record_button = ctk.CTkButton(
            self.panel_frame,
            text="Record",
            command=self.record
        )
        self.record_button.grid(row=ACTION_ROW + 1, column=0, pady=5)
        self.record_button.grid_remove()

        self.tare_button = ctk.CTkButton(
            self.panel_frame,
            text="Tare / Zero",
            command=self.tare
        )
        self.tare_button.grid(row=ACTION_ROW + 2, column=0, pady=5)
        self.tare_button.grid_remove()

        self.reset_button = ctk.CTkButton(
            self.panel_frame,
            text="Reset / Gain",
            command=self.rst
        )
        self.reset_button.grid(row=ACTION_ROW + 3, column=0, pady=5)
        self.reset_button.grid_remove()

        self.save_button = ctk.CTkButton(
            self.panel_frame,
            text="Save Image",
            command=self.save_im
        )
        self.save_button.grid(row=ACTION_ROW + 4, column=0, pady=(5, 10))
        self.save_button.grid_remove()

        self.stop_button = ctk.CTkButton(
            self.panel_frame,
            text="STOP",
            fg_color="#d13b30",
            hover_color="#b03028",
            command=self.stop_all
        )
        self.stop_button.grid(row=ACTION_ROW + 5, column=0, pady=(10, 10))
        self.stop_button.grid_remove()

        # -----------------------------
        # Dev Terminal
        # -----------------------------
        self.setup_terminal()

    def _set_config_controls_state(self, enabled: bool):
        state = "normal" if enabled else "disabled"

        self.mode_select.configure(state=state)
        self.sensor_select.configure(state=state)
        self.acq_select.configure(state=state)
        self.scan_entry_x.configure(state=state)
        self.scan_entry_y.configure(state=state)

    def change_sensor(self, sensor_name):
        rows, cols = SENSOR_PROFILES[sensor_name]
        self.sensor_rows = rows
        self.sensor_cols = cols

        self.updating = False
        self.scan_active = False
        self.scan_x_step = 0
        self.scan_y_step = 0
        self.scan_buffer = None

        self.data = np.zeros((rows, cols))
        self.offset = np.zeros_like(self.data)

        self.img.set_array(self.data)
        self.img.set_extent((-0.5, cols - 0.5, rows - 0.5, -0.5))
        self.ax.set_xlim(-0.5, cols - 0.5)
        self.ax.set_ylim(rows - 0.5, -0.5)

        self.canvas.draw_idle()

    def update_controls_ui(self):
        widgets = [
            self.scan_label,
            self.scan_entry_x,
            self.scan_entry_y,
            self.scan_start_btn,
            self.scan_next_btn,
            self.capture_button,
            self.record_button,
            self.tare_button,
            self.reset_button,
            self.stop_button,
        ]

        for w in widgets:
            w.grid_remove()

        # ----------------------------
        # IDLE / READY
        # ----------------------------
        if self.ui_state in ("IDLE", "READY"):
            self._set_config_controls_state(True)

            self.scan_start_btn.grid()

            if self.acq_mode == "SNAPSHOT":
                self.scan_label.grid()
                self.scan_entry_x.grid()
                self.scan_entry_y.grid()

        # ----------------------------
        # RUNNING / SCANNING
        # ----------------------------
        elif self.ui_state in ("RUNNING", "SCANNING"):
            self._set_config_controls_state(False)

            self.capture_button.grid()
            self.record_button.grid()
            self.tare_button.grid()
            self.reset_button.grid()
            self.stop_button.grid()

            if self.ui_state == "SCANNING":
                self.scan_next_btn.grid()

    def change_acq_mode(self, mode):
        self.acq_mode = mode
        self.ui_state = "READY"
        self.update_controls_ui()

    def capture_snapshot(self):
        if not self.serial_port or not self.serial_port.is_open:
            print("Serial not open — cannot capture snapshot")
            return

        # Arm snapshot
        self.snapshot_pending = True
        self.updating = False

        # Ask Arduino for ONE frame
        try:
            self.serial_port.write(b"snapshot\n")
            self.terminal.insert("end", "Snapshot requested\n")
        except Exception as e:
            print("Snapshot request failed:", e)

    def start_scan(self):
        rows = self.sensor_rows
        cols = self.sensor_cols

        if self.acq_mode != "SNAPSHOT":
            self.ui_state = "RUNNING"
            self.update_controls_ui()
            return

        try:
            self.scan_x_steps = int(self.scan_entry_x.get())
            self.scan_y_steps = int(self.scan_entry_y.get())
            if self.scan_x_steps <= 0 or self.scan_y_steps <= 0:
                raise ValueError
        except ValueError:
            print("Invalid X/Y interleaving steps")
            return

        # Reset scan state
        self.scan_x_step = 0
        self.scan_y_step = 0
        self.scan_active = True
        self.ui_state = "SCANNING"

        total_rows = rows * self.scan_y_steps
        total_cols = cols * self.scan_x_steps

        self.scan_buffer = np.zeros((total_rows, total_cols))
        self.data = self.scan_buffer

        # Rebind image
        self.img.set_array(self.data)
        self.img.set_extent((-0.5, total_cols - 0.5, total_rows - 0.5, -0.5))
        self.ax.set_xlim(-0.5, total_cols - 0.5)
        self.ax.set_ylim(total_rows - 0.5, -0.5)

        self.canvas.draw_idle()
        self.update_controls_ui()

        # Trigger first snapshot
        self.snapshot_pending = True
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.write(b"snapshot\n")

    def scan_next(self):
        if not self.scan_active:
            return

        if self.scan_y_step >= self.scan_y_steps:
            self.scan_active = False
            self.ui_state = "READY"
            self.update_controls_ui()
            return

        self.snapshot_pending = True

        if self.serial_port and self.serial_port.is_open:
            self.serial_port.write(b"snapshot\n")

    def stop_all(self):
        # Stop acquisition
        self.updating = False
        self.recording = False
        self.scan_active = False
        self.scan_started = False
        self.snapshot_pending = False

        # Restore defaults
        self.update_interval = 250
        self.speed_slider.set(250)
        self.speed_value_slider.configure(text="250ms")

        # Reset buttons
        self.record_button.configure(text="Record", command=self.record)

        # Reset UI
        self.ui_state = "READY"
        self.update_controls_ui()

    def update_plot(self):
        if self.updating:

            # Update plot
            if (self.mode == "Normal" or self.mode == "Color"):
                if (self.recording):
                    self.tmp_gif.append(self.data + self.offset)

                self.img.set_data(self.data + self.offset)
                self.img.set(clim=[0, 3.3])
                self.canvas.draw()
                for t in list(self.ax.texts):
                    t.remove()
                for (i, j), z in np.ndenumerate(self.data + self.offset):
                    self.ax.text(j, i, f"{z:.2f}", ha='center', va='center', size=12)
            else:
                # functions of thesholding and ESD Capture
                tmp = (self.data + self.offset) > self.threshold

                if (self.mode == "ESD Capture"):
                    # add capture function here for ESD capture.
                    if (True):
                        self.capture()
                        print("ESD Capture Invoked.")

                self.img.set_data(tmp)
                self.img.set(clim=[0, 1])
                self.canvas.draw()
                self.ax.texts.clear()
                for (i, j), z in np.ndenumerate(self.data):
                    self.ax.text(j, i, f"{z:.2f}", ha='center', va='center', size=12)
            
            # Schedule next update
            self.after(self.update_interval, self.update_plot)

    def get_available_ports(self):
        ports = serial.tools.list_ports.comports()
        return [port.device for port in ports]

    def refresh_ports(self):
        ports = self.get_available_ports()
        self.port_option.configure(values=ports)
        if ports:
            self.port_option.set(ports[0])
        else:
            self.port_option.set("")

    def toggle_serial_connection(self):
        if self.serial_port and self.serial_port.is_open:
            self.close_serial_port()
        else:
            self.open_serial_port()

    def open_serial_port(self):
        port = self.port_option.get()
        baud = int(self.baud_option.get())
        
        try:
            self.serial_port = serial.Serial(
                port=port,
                baudrate=baud,
                timeout=1,
                parity=serial.PARITY_EVEN,
                stopbits=serial.STOPBITS_TWO,   # <-- ensure 2 stop bits to match Arduino SERIAL_8E2
                xonxoff=True,      # enable software flow control
                rtscts=False,
                dsrdtr=False
            )
            time.sleep(1)
            self.serial_event.clear()
            self.serial_thread = Thread(target=self.read_serial_data)
            self.serial_thread.start()
            
            self.connect_btn.configure(text="Close Port")
            self.port_option.configure(state="disabled")
            self.baud_option.configure(state="disabled")
            self.refresh_btn.configure(state="disabled")
            self.terminal.insert("end", f"Connected to {port} @ {baud} baud\n")
            
        except Exception as e:
            print(f"Error: {str(e)}\n")
            self.serial_port = None

    def close_serial_port(self):
        if self.serial_port and self.serial_port.is_open:
            self.serial_event.set()
            self.serial_port.close()
            self.serial_thread.join()

        self.serial_port = None
        self.ui_state = "READY"
        self.update_controls_ui()

    def read_serial_data(self):
        buffer = ""

        while not self.serial_event.is_set():
            try:
                char = self.serial_port.read().decode(errors="ignore")

                if char:
                    buffer += char

                    # Prevent runaway buffer
                    if len(buffer) > 4096:
                        buffer = ""

                    # Look for a complete frame < ... >
                    while '<' in buffer and '>' in buffer:
                        start = buffer.find('<')
                        end   = buffer.find('>')

                        frame = buffer[start + 1:end]   # strip < >
                        buffer = buffer[end + 1:]       # consume buffer

                        # NO checksum, push raw payload
                        self.data_queue.put(frame.strip() + "\n")

            except Exception as e:
                self.data_queue.put(f"Error: {str(e)}\n")

            time.sleep(0.001)


    def _parse_and_update(self, data):
        parts = data.split("|")
        values_str = parts[0].strip().split()

        rowNum, colNum = self.sensor_rows, self.sensor_cols
        expected = rowNum * colNum

        if len(values_str) < expected:
            return

        values = np.array([float(v) for v in values_str[:expected]])
        frame = np.flip(values.reshape(rowNum, colNum), axis=1)

        if self.scan_active:
            r0 = self.scan_y_step * rowNum
            c0 = self.scan_x_step * colNum

            self.scan_buffer[r0:r0+rowNum, c0:c0+colNum] = frame
            self.img.set_array(self.scan_buffer)

            # Advance raster
            self.scan_x_step += 1
            if self.scan_x_step >= self.scan_x_steps:
                self.scan_x_step = 0
                self.scan_y_step += 1

            # Finish raster
            if self.scan_y_step >= self.scan_y_steps:
                self.scan_active = False
                self.ui_state = "READY"
                self.update_controls_ui()

        else:
            self.data = frame
            self.img.set_array(self.data)

        self.canvas.draw_idle()

        # SAVE ONLY AFTER FULL RASTER
        if self.acq_mode == "SNAPSHOT" and not self.scan_active and self.snapshot_pending:
            self.save_im()
            self.snapshot_pending = False

    def process_serial_data(self):
        latest = None
        while not self.data_queue.empty():
            latest = self.data_queue.get()

        if latest:
            self._parse_and_update(latest)

        self.after(100, self.process_serial_data)

    def send_serial_message(self):
        if self.serial_port and self.serial_port.is_open:
            message = self.entry.get() + "\n"
            try:
                self.serial_port.write(message.encode())
                self.terminal.insert("end", f"Sent: {message}")
                self.entry.delete(0, "end")
            except Exception as e:
                self.terminal.insert("end", f"Send error: {str(e)}\n")
        else:
            # self.terminal.insert("end", "Port not open!\n")
            print("random failed")

    def clear_terminal(self):
        self.terminal.delete("1.0", "end")

    def on_closing(self):
        self.close_serial_port()
        self.destroy()

    def update_mode(self, mode):
        # update mode here
        if (mode == "Normal"):
            self.mode = "Normal"
            self.img.set_cmap("plasma")
            self.img.set_data(self.data)
            self.img.set(clim=[0, 3.3]) # may need to change accordingly of readings
            self.canvas.draw()
        elif (mode == "Color"):
            self.mode = "Color"
            self.img.set_cmap("gist_rainbow")
            self.img.set_data(self.data)
            self.img.set(clim=[0, 3.3]) # may need to change accordingly of readings
            self.canvas.draw()
        elif (mode == "Threshold"):
            self.mode = "Threshold"
            self.threshold = 1.5   # Change threshold here.
            self.img.set_cmap("gray")
            self.img.set_data(self.data[:,:] > self.threshold)
            self.img.set(clim=[0, 1])
            self.canvas.draw()
        elif (mode == "ESD Capture"):
            self.mode = "ESD Capture"
            self.threshold = 3.2 # Change threshold here.
            self.img.set_cmap("gray")
            self.img.set_data(self.data[:,:] > self.threshold)
            self.img.set(clim=[0, 1])
            self.canvas.draw()

    def capture(self):
        if self.acq_mode != "VIDEO":
            return

        self.updating = not self.updating

        if self.updating:
            self.ui_state = "RUNNING"
            if self.serial_port and self.serial_port.is_open:
                self.serial_port.write(b"start")
            self.update_plot()
        else:
            self.ui_state = "READY"

        self.update_controls_ui()

    def save_im(self):
        os.makedirs("./Captured", exist_ok=True)
        idx = len(os.listdir("./Captured"))
        self.fig.savefig(f"./Captured/{idx}.png")
    
    def tare(self):
        self.offset = -self.data

        self.tare_button.grid_remove()
        self.reset_button.grid(row=15, column=0, pady=5)

        self.img.set_data(self.data + self.offset)
        self.canvas.draw()
        
    def rst(self):
        self.offset = np.zeros_like(self.data)

        self.reset_button.grid_remove()
        self.tare_button.grid(row=14, column=0, pady=5)

        self.img.set_data(self.data)
        self.canvas.draw()

    def update_gain(self, gain):
        # update gain factor
        self.gain = gain
        self.gain_value_slider.configure(text=f"{round(self.gain, 2):.2f}")

    def update_speed(self, value):
        self.update_interval = int(value)
        self.speed_value_slider.configure(text=f"{self.update_interval}ms")
    
    def record(self):
        if self.recording:
            return  # already recording, do nothing

        self.recording = True
        self.tmp_gif = []

        # Button state
        self.record_button.configure(
            text="Stop Recording",
            command=self.stop_record
        )

        # Disable config controls (NOT hide)
        self.speed_slider.configure(state="disabled")
        self.gain_slider.configure(state="disabled")

        # Fast update
        self.update_interval = 33
        self.speed_slider.set(1)
        self.speed_value_slider.configure(text="1ms")

    def stop_record(self):
        if not self.recording:
            return

        self.recording = False

        # Restore button
        self.record_button.configure(
            text="Record",
            command=self.record
        )

        # Restore controls
        self.speed_slider.configure(state="normal")
        self.gain_slider.configure(state="normal")

        self.update_interval = 250
        self.speed_slider.set(250)
        self.speed_value_slider.configure(text="250ms")

        # 🚨 Guard: nothing recorded
        if not self.tmp_gif:
            print("No frames recorded — skipping GIF export")
            return

        self.export_gif(
            data=self.tmp_gif,
            cmap_type=self.img.get_cmap(),
            output_file=self._next_capture_filename(".gif")
        )

        self.tmp_gif = []

    def export_gif(self, data, output_file, cmap_type, fps=8):
        # Create figure and axis without displaying
        fig = Figure(figsize=(6, 6))
        ax = fig.add_subplot(111)
        fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
        ax.axis('off')
        
        # Initialize image plot
        img = ax.imshow(data[0], cmap=cmap_type, aspect='auto', origin='lower')
        
        # Animation function
        def animate(i):
            img.set_data(np.flip(data[i], axis=0))
            return [img]
        
        # Create animation
        ani = animation.FuncAnimation(
            fig,
            animate,
            frames=len(data),
            blit=True
        )
        
        # Save directly to GIF
        writer = animation.PillowWriter(fps=fps)
        ani.save(output_file, writer=writer)
        plt.close(fig)  # Clean up figure

    def start_drag(self, event):
        global x, y
        x = event.x
        y = event.y

    def stop_drag(self, event):
        global x, y
        x = 0
        y = 0

    def move_window(self, event):
        self.geometry(f"+{event.x_root - 25}+{event.y_root - 45}")

    def minimize_window(self, Event=None):
        self.state("withdrawn")
        self.overrideredirect(False)
        self.state("iconic")

    def recover_window(self, Event=None):
        self.state("normal")
        self.overrideredirect(True)

    def toggle_terminal(self, Event=None):
        if self.debug:
            self.dev_frame.grid_forget()
            self.debug_button._fg_color = "#dd3b30"
            self.debug = False
        else:
            self.dev_frame.grid(row=2, column=0, padx=(2.5,10), pady=10, sticky="e")
            self.debug_button._fg_color = "#49eb34"
            self.debug = True
'''
    def windowHandler(self, Event=None):
        if (self.state == "normal" and Event == "<Unmap>"):
            self.minimize_window

        elif (self.state == "iconic" and Event == "<Map>"):
            self.recover_window
'''
'''
class WindowHandler(ctk.CTk):
    def __init__(self, app):
        self.app = app
        self.geometry("1x1")
        self.state = "normal"
        self.bind("<Map>", app.recover_window)
'''
        
if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()