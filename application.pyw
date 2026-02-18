import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
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

ROW_NUM = 6
COL_NUM = 6

# Set CustomTkinter appearance
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("themes/coffee.json")

class App(ctk.CTk):
    def __init__(self, update_interval=250):
        super().__init__()
        # self.overrideredirect(True) # removes default windows title bar
        # self.bind("<Map>", self.recover_window)

        # Initialize
        self.mode = "Normal"
        self.gain = 1 # to be passed into port
        self.data = np.random.rand(ROW_NUM, COL_NUM) # Initial data (define sensor array dimension here)
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

        # Initialize plot
        self.setup_plot()
        self.setup_controls()
        
        # Initialize update flag
        self.update_interval = update_interval
        self.updating = False

        # check for serial
        self.after(200, self.process_serial_data)

    def setup_plot(self):
        # Create matplotlib figure
        self.fig = Figure(figsize=(7, 6), dpi=100)
        self.ax = self.fig.add_subplot(111)
        
        self.img = self.ax.imshow(
            self.data,
            interpolation="nearest",
            cmap="plasma",
            aspect="1.0",
            clim=[0, 2] # may need to change accordingly of readings
        )
        for (i, j), z in np.ndenumerate(self.data):
            self.ax.text(j, i, f"{z:.2f}", ha='center', va='center', size=12)
        self.fig.colorbar(self.img, ax=self.ax)
        
        # Embed in CustomTkinter
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
        # Serial Port Controls
        self.setup_serial_controls()

        # Control panel widgets
        self.title_label = ctk.CTkLabel(self.panel_frame, text="Controls", font=("Arial", 20, "bold"))
        self.title_label.grid(row=0, column=0, pady=(10,5))

        # Colormap selector
        self.mode_label = ctk.CTkLabel(self.panel_frame, text="Mode Selection:")
        self.mode_label.grid(row=1, column=0, pady=(0, 5))
        
        self.mode_select = ctk.CTkOptionMenu(
            self.panel_frame,
            values=["Normal", "Color", "Threshold"],
            # values=["Normal", "Color", "Threshold", "ESD Capture"],
            command=self.update_mode
        )
        self.mode_select.grid(row=2, column=0, pady=5)
        self.mode_select.set("Normal")

        # Update interval slider
        self.speed_frame = ctk.CTkFrame(master=self.panel_frame)
        self.speed_frame.grid_columnconfigure(2, weight=2)
        self.speed_frame.grid_rowconfigure(1, weight=1)

        self.speed_label = ctk.CTkLabel(self.speed_frame, text="Refresh Speed:")
        self.speed_label.grid(row=0, column=0, padx=12.5, sticky="w")
        
        self.speed_slider = ctk.CTkSlider(
            self.speed_frame,
            from_=2000,
            to=250,
            number_of_steps=50,
            command=self.update_speed
        )
        self.speed_slider.grid(row=1, column=0, columnspan=2, padx=5, pady=10, sticky="ew")

        self.speed_value_slider = ctk.CTkLabel(self.speed_frame, text=str(self.update_interval) + "ms")
        self.speed_value_slider.grid(row=0, column=1, padx=10, pady=0, sticky="e")

        self.speed_frame.grid(row=3, column=0, pady=5, padx=10)
        self.speed_slider.set(self.update_interval)

        # Update gain slider
        self.gain_frame = ctk.CTkFrame(master=self.panel_frame)
        self.gain_frame.grid_columnconfigure(2, weight=2)
        self.gain_frame.grid_rowconfigure(1, weight=1)

        self.gain_label = ctk.CTkLabel(self.gain_frame, text="Gain:")
        # self.gain_label.grid(row=0, column=0, padx=12.5, sticky="w")
        
        self.gain_slider = ctk.CTkSlider(
            self.gain_frame,
            from_=1,
            to=10,
            number_of_steps=50,
            command=self.update_gain
        )

        # self.gain_slider.grid(row=1, column=0, columnspan=2, padx=5, pady=10, sticky="ew")

        self.gain_value_slider = ctk.CTkLabel(self.gain_frame, text=f"{self.gain:.2f}")
        # self.gain_value_slider.grid(row=0, column=1, padx=10, pady=0, sticky="e")

        # self.gain_frame.grid(row=4, column=0, pady=5, padx=10)
        self.gain_slider.set(self.gain)

        # Capture button
        self.capture_button = ctk.CTkButton(
            self.panel_frame,
            text="Start",
            command=self.capture
        )

        # Record button
        self.record_button = ctk.CTkButton(
            self.panel_frame,
            text="Record",
            command=self.record
        )

        # Reset/Auto tune gain Button
        self.reset_button = ctk.CTkButton(
            self.panel_frame,
            text="Reset / Gain",
            command=self.rst
        )

        # Tare/Zero Button
        self.tare_button = ctk.CTkButton(
            self.panel_frame,
            text="Tare / Zero",
            command=self.tare
        )

        # Save Image Button
        self.save_button = ctk.CTkButton(
            self.panel_frame,
            text="Save Image",
            command=self.save_im
        )

        # Dev: serial terminal
        self.setup_terminal()

    def update_plot(self):
        if self.updating:

            # Update plot
            if (self.mode == "Normal" or self.mode == "Color"):
                if (self.recording):
                    self.tmp_gif.append(self.data + self.offset)

                self.img.set_data(self.data + self.offset)
                self.img.set(clim=[0,5])
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

            self.capture_button.grid(row=5, column=0, pady=10) # enable start/capture control button
            
        except Exception as e:
            print(f"Error: {str(e)}\n")
            self.serial_port = None

    def close_serial_port(self):
        if self.serial_port and self.serial_port.is_open:
            self.serial_event.set()
            self.serial_port.close()
            self.serial_thread.join()
                
            self.connect_btn.configure(text="Open Port")
            self.port_option.configure(state="normal")
            self.baud_option.configure(state="normal")
            self.refresh_btn.configure(state="normal")
            self.terminal.insert("end", "Port closed\n")

            self.capture()

            self.capture_button.grid_forget() # disable start/capture control button

    def read_serial_data(self):
        buffer = ""

        while not self.serial_event.is_set():
            try:
                char = self.serial_port.read().decode(errors="ignore")

                if char:
                    buffer += char

                    if len(buffer) > 4096:
                        buffer = ""     # full resync if buffer gets too large (garbage/spam)

                    # check for full frame <.....>
                    if '<' in buffer and '>' in buffer:
                        start = buffer.find('<')
                        end   = buffer.find('>')

                        frame = buffer[start+1:end]  # remove < >
                        buffer = buffer[end+1:]      # clean buffer

                        # split: "values | checksum"
                        if '|' in frame:
                            payload, checksum_hex = frame.rsplit('|', 1)
                            checksum_hex = checksum_hex.strip()

                            calc = 0
                            for c in payload:
                                calc ^= ord(c)

                            # convert calc to 2-digit hex string
                            calc_hex = format(calc, "02X")

                            if calc_hex == checksum_hex:
                                self.data_queue.put(payload + "\n")   # valid
                            else:
                                print("Checksum mismatch:", calc_hex, checksum_hex)

            except Exception as e:
                self.data_queue.put(f"Error: {str(e)}\n")

            time.sleep(0.005)


    # May need to play around with this function
    def process_serial_data(self):
        while not self.data_queue.empty():

            data = self.data_queue.get()

            if (not self.updating):
                self.terminal.insert("end", data)
                self.terminal.see("end")

            else:
                data = data.split(" ")

                rowNum = ROW_NUM
                colNum = COL_NUM
                # print(data) # for debug purpose
                try:
                    data = np.array([float(i) for i in data[:(rowNum*colNum)]]).reshape(rowNum, colNum)
                    self.data = np.flip(data, axis=1)
                    if (self.initFlag):
                        self.offset = np.zeros(self.data.shape)
                        self.initFlag = False
                except Exception as e:
                    print("unknown error: ", e)
                    print(data)
                

        self.after(200, self.process_serial_data)

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
            self.img.set(clim=[-10, 10]) # may need to change accordingly of readings
            self.canvas.draw()
        elif (mode == "Color"):
            self.mode = "Color"
            self.img.set_cmap("gist_rainbow")
            self.img.set_data(self.data)
            self.img.set(clim=[-10, 10]) # may need to change accordingly of readings
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
        self.updating = not self.updating
        if not self.updating:
            self.capture_button.configure(text="Continue")
            self.record_button.grid_forget()
            self.save_button.grid(row=7, column=0, pady=(2.5,10))
            if (np.all(self.offset) == 0):
                self.tare_button.grid(row=8, column=0, pady=(2.5,10))

        else:
            if self.serial_port and self.serial_port.is_open:
                message = "start"
                try:
                    self.serial_port.write(message.encode())
                    self.terminal.insert("end", f"Sent: {message}")
                    self.entry.delete(0, "end")
                except Exception as e:
                    self.terminal.insert("end", f"Send error: {str(e)}\n")
            else:
                self.terminal.insert("end", "Port not open!\n")
            self.terminal.insert("end", "Port not open!\n")
            self.record_button.grid(row=6, column=0, pady=(2.5,10))
            self.capture_button.configure(text="Capture")
            self.save_button.grid_forget()
            self.tare_button.grid_forget()
            self.update_plot()

    def save_im(self):
        # saving image to folder "Captured", one liner to improve speed not result from gen AI
        self.fig.savefig("./Captured/" + str(np.amax(np.array(list(map(int, [os.path.splitext(file)[0] for file in os.listdir("./Captured")])))) + 1) if len(os.listdir("./Captured")) else "./Captured/" + str(0))
    
    def tare(self):
        # add code for taring/zeroing 
        self.offset = -(self.data)

        self.reset_button.grid(row=8, column=0, pady=(2.5,10))
        self.tare_button.grid_forget()

        self.img.set_data(self.data + self.offset)
        self.canvas.draw()
        
    def rst(self):
        self.offset = np.zeros(self.data.shape)

        self.reset_button.grid_forget()
        if not self.updating:
            self.tare_button.grid(row=8, column=0, pady=(2.5,10))

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
        self.record_button.configure(text="Stop Recording", command=self.stop_record)
        self.capture_button.grid_forget()
        self.reset_button.grid_forget()
        self.update_interval = 1
        self.speed_slider.set(1)
        self.speed_value_slider.configure(text="1ms")
        self.speed_slider.configure(state="disabled")
        self.gain_slider.configure(state="disabled")
        self.tmp_gif = []
        self.recording = True

    def stop_record(self):
        # export to gif, time unit 0.25 second per frame
        self.export_gif(data = self.tmp_gif, cmap_type = self.img.get_cmap(), output_file = "./Captured/" + str(np.amax(np.array(list(map(int, [os.path.splitext(file)[0] for file in os.listdir("./Captured")])))) + 1) + ".gif" if len(os.listdir("./Captured")) else "./Captured/" + str(0) + ".gif")

        self.recording = False
        self.tmp_gif = []
        self.gain_slider.configure(state="normal")
        self.speed_slider.configure(state="normal")
        self.speed_slider.set(250)
        self.update_interval = 250
        self.speed_value_slider.configure(text=f"{self.update_interval}ms")
        if (np.all(self.offset) != 0):
            self.reset_button.grid(row=8, column=0, pady=(2.5,10))
        self.capture_button.grid(row=5, column=0, pady=10)
        self.record_button.configure(text="Record", command=self.record)

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