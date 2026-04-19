import tkinter as tk
root = tk.Tk()
var = tk.StringVar()
tk.Label(root, textvariable=var).pack()
def open_picker():
    top = tk.Toplevel(root)
    # create lambda exactly as in gui.py
    tk.Button(top, text="Hello", command=lambda e="😊": [var.set(var.get() + e), top.destroy()]).pack()
    
tk.Button(root, text="Open", command=open_picker).pack()

def click_sim():
    open_picker()
    # Find toplevel and click
    for c in root.winfo_children():
        if isinstance(c, tk.Toplevel):
            top = c
            for btn in top.winfo_children():
                if isinstance(btn, tk.Button):
                    btn.invoke()
                    return
    
root.after(500, click_sim)
root.after(1000, root.quit)
root.mainloop()
print("Var is:", var.get())
