#!/usr/bin/env python3
"""Tiny touch and keyboard sketchpad; controls/dialogs fit the native screen."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
import signal
import time
import tkinter as tk
from PIL import ImageTk
from drawing import Drawing, WIDTH, HEIGHT, PALETTE, SIZES
from storage import Paths, directory, read_state, validate_path, write_state

APP_ID = 'io.vitrallis.sketch'
BG, PANEL, TEXT, ACCENT = '#101820', '#203140', '#eff5fa', '#64d9bb'


class App:
    def __init__(self, root, paths=None):
        self.root, self.paths, self.model = root, paths or Paths(APP_ID), Drawing()
        self.closed, self.frame, self.overlay, self.dialog_kind = False, None, None, None
        self.cursor, self.pen, self.photo, self.palette = [WIDTH//2, HEIGHT//2], False, None, None
        state = read_state(self.paths.state / 'settings.json')
        self.model.color = state.get('color',0) if type(state.get('color')) is int and 0 <= state['color'] < len(PALETTE) else 0
        self.model.size = state.get('size',1) if type(state.get('size')) is int and 0 <= state['size'] < len(SIZES) else 1
        root.title('Sketch')
        root.geometry('480x272')
        root.minsize(480,272)
        root.configure(bg=BG)
        if root.tk.call('tk', 'windowingsystem') == 'x11': root.wm_client(root.tk.call('info', 'hostname'))
        commands = [('New', lambda: self.confirm(self.model.new)), ('Open', self.open_dialog), ('Save', self.save),
                    ('Undo', self.undo), ('Pen', self.tool), ('Color', self.colors), ('Exit', lambda: self.confirm(self.close))]
        for i,(label, callback) in enumerate(commands):
            button=self.button(root,label,callback)
            button.place(x=8+i*67,y=4,width=62,height=30)
            if label=='Pen':self.tool_button=button
        self.canvas = tk.Canvas(root, bg='white', highlightthickness=0, takefocus=True)
        self.canvas.place(x=8,y=40,width=WIDTH,height=HEIGHT)
        self.item = self.canvas.create_image(0,0,anchor='nw')
        self.marker = self.canvas.create_rectangle(0,0,0,0,outline='#38a3bc',width=1)
        self.canvas.bind('<ButtonPress-1>', self.press)
        self.canvas.bind('<B1-Motion>', self.motion)
        self.canvas.bind('<ButtonRelease-1>', self.release)
        self.footer = tk.Label(root, bg=BG,fg=TEXT,anchor='w',font=('DejaVu Sans',-11))
        self.footer.place(x=8,y=239,width=464,height=29)
        root.bind('<Key>', self.key)
        root.protocol('WM_DELETE_WINDOW', lambda: self.confirm(self.close))
        self.canvas.focus_set()
        self.render()
        self.signal_job=root.after(250,self.poll_signals)

    def poll_signals(self):
        # Let idle Linux Tk return to Python for TERM/INT; this never redraws.
        if not self.closed:self.signal_job=self.root.after(250,self.poll_signals)

    def button(self, parent, label, callback):
        b = tk.Button(parent,text=label,command=callback,bg=PANEL,
                      fg=BG if self.root.tk.call('tk','windowingsystem')=='aqua' else TEXT,
                      relief='flat', bd=0, highlightcolor=ACCENT,highlightthickness=2,
                      takefocus=True,font=('DejaVu Sans',-12))
        b.bind('<Return>',lambda e:(callback(),'break')[1])
        return b

    def render(self):
        self.frame = None
        if self.closed: return
        self.photo = ImageTk.PhotoImage(self.model.image)
        self.canvas.itemconfigure(self.item,image=self.photo)
        x,y = self.cursor
        self.canvas.coords(self.marker,x-3,y-3,x+3,y+3)
        self.canvas.tag_raise(self.marker)
        self.tool_button.configure(text='Erase' if self.model.eraser else 'Pen')
        self.footer.configure(text=f'{"Eraser" if self.model.eraser else "Pencil"} {SIZES[self.model.size]}px · {"Unsaved" if self.model.dirty else "Saved"} · Arrows cursor · Space pen · ? help')
        if self.model.warning and not self.model.dirty:
            self.footer.configure(text=self.model.warning)

    def changed(self):
        if self.frame is None:
            self.frame = self.root.after(34,self.render)

    def press(self,event):
        if self.overlay: return
        self.canvas.focus_set()
        self.pen = False
        self.model.begin(event.x,event.y)
        self.cursor[:] = self.model.point(event.x,event.y)
        self.changed()

    def motion(self,event):
        self.model.stroke(event.x,event.y)
        self.cursor[:] = self.model.point(event.x,event.y)
        self.changed()

    def release(self,event):
        self.motion(event)
        self.model.end()

    def undo(self,redo=False):
        self.pen=False
        self.model.undo(redo)
        self.changed()

    def tool(self):
        self.model.eraser = not self.model.eraser
        self.changed()

    def colors(self):
        if self.overlay: return
        if self.palette:
            self.palette.destroy()
            self.palette=None
            self.canvas.focus_set()
            return
        self.palette=tk.Frame(self.root,bg=PANEL)
        self.palette.place(x=8,y=40,width=464,height=42)
        for i,color in enumerate(PALETTE):
            b=self.button(self.palette,str(i+1),lambda i=i:self.choose(i))
            b.configure(bg=color,fg=BG if i or self.root.tk.call('tk','windowingsystem')=='aqua' else TEXT)
            b.place(x=4+i*57,y=4,width=51,height=34)
        self.palette.winfo_children()[0].focus_set()

    def choose(self,index):
        self.model.color,self.model.eraser=index,False
        if self.palette: self.colors()
        self.changed()

    def dismiss(self):
        if self.overlay:
            self.overlay.destroy()
        self.overlay,self.dialog_kind=None,None
        self.canvas.focus_set()

    def dialog(self,title,kind):
        if self.palette: self.colors()
        self.pen=False
        self.model.end()
        self.dismiss()
        self.dialog_kind=kind
        self.overlay=tk.Frame(self.root,bg=PANEL,highlightbackground=ACCENT,highlightthickness=2)
        self.overlay.place(x=16,y=40,width=448,height=194)
        tk.Label(self.overlay,text=title,bg=PANEL,fg=TEXT,font=('DejaVu Sans',-15,'bold')).place(x=8,y=4,width=428,height=25)
        self.message=tk.Label(self.overlay,text='',bg=PANEL,fg=TEXT,font=('DejaVu Sans',-11),anchor='w')
        self.message.place(x=8,y=132,width=428,height=20)
        self.button(self.overlay,'Cancel [Esc]',self.dismiss).place(x=8,y=155,width=132,height=30)

    def confirm(self,callback):
        if not self.model.dirty:
            callback()
            self.changed() if not self.closed else None
            return
        self.dialog('Unsaved drawing · save or discard?', 'confirm')
        self.button(self.overlay,'Save',self.save).place(x=152,y=155,width=132,height=30)
        def discard():
            self.dismiss()
            self.model.dirty=False
            callback()
            if not self.closed: self.changed()
        self.button(self.overlay,'Discard',discard).place(x=296,y=155,width=132,height=30)
        self.overlay.winfo_children()[2].focus_set()

    def open_dialog(self):
        if self.model.dirty:
            self.confirm(self._open_dialog)
        else: self._open_dialog()

    def _open_dialog(self):
        self.dialog('Open from Sketch Documents', 'open')
        self.files=[]
        try:
            self.files=sorted([p for p in self.paths.documents.iterdir() if not p.is_symlink() and p.is_file() and p.suffix.lower() in ('.png','.jpg','.jpeg')],key=lambda p:p.name.casefold())[:200]
        except OSError: pass
        self.file_list=tk.Listbox(self.overlay,bg=BG,fg=TEXT,selectbackground='#30576a',font=('DejaVu Sans',-13),exportselection=False)
        self.file_list.place(x=8,y=34,width=428,height=95)
        for p in self.files:self.file_list.insert('end',p.name)
        if not self.files:self.message.configure(text='No images here yet. Save a drawing to get started.')
        self.file_list.selection_set(0)
        self.file_list.bind('<Return>',lambda e:(self.open_selected(),'break')[1])
        self.file_list.bind('<Double-Button-1>',lambda e:self.open_selected())
        self.button(self.overlay,'Open',self.open_selected).place(x=296,y=155,width=132,height=30)
        self.file_list.focus_set()

    def open_selected(self):
        if not self.file_list.curselection() or not self.files:return
        try:
            self.model.open(self.files[self.file_list.curselection()[0]])
            self.dismiss()
            self.changed()
        except (OSError,ValueError) as error:self.message.configure(text=str(error)[:64])

    def save(self,save_as=False):
        if self.model.path and not save_as:
            try:
                self.model.save()
                self.dismiss()
                self.changed()
                return
            except (OSError,ValueError) as error:
                self.footer.configure(text=f'Save failed: {str(error)[:58]}')
                return
        self.dialog('Save PNG to Sketch Documents','save')
        self.filename=tk.Entry(self.overlay,font=('DejaVu Sans',-15))
        self.filename.place(x=8,y=42,width=428,height=32)
        self.filename.insert(0,self.model.path.name if self.model.path else 'Drawing.png')
        self.filename.select_range(0,'end')
        self.filename.bind('<Return>',lambda e:(self.save_named(),'break')[1])
        self.save_button=self.button(self.overlay,'Save PNG',self.save_named)
        self.save_button.place(x=296,y=155,width=132,height=30)
        self.filename.focus_set()

    def save_named(self,overwrite=False):
        name=self.filename.get().strip()
        if not name or '/' in name or '\\' in name or name in ('.','..') or len(name)>120 or any(not c.isprintable() for c in name):
            self.message.configure(text='Use a filename without folders or control characters')
            return
        if not name.lower().endswith('.png'):name+='.png'
        target=self.paths.documents/name
        if target.exists() and not overwrite:
            self.message.configure(text='Already exists · select Replace to confirm')
            self.save_button.configure(text='Replace',command=lambda:self.save_named(True))
            return
        try:
            self.model.save(target)
            self.dismiss()
            self.changed()
        except (OSError,ValueError) as error:self.message.configure(text=f'Save failed: {str(error)[:49]}')

    def key(self,event):
        key,char=event.keysym,event.char.lower()
        if key=='Escape':
            if self.overlay:self.dismiss()
            elif self.palette:self.colors()
            else:self.confirm(self.close)
            return 'break'
        if self.overlay:return None
        if char=='n':self.confirm(self.model.new)
        elif char=='o':self.open_dialog()
        elif char=='s':self.save(bool(event.state & 1))
        elif char=='u' or (event.state&4 and char=='z'):self.undo()
        elif char=='y':self.undo(True)
        elif char=='e':self.tool()
        elif char=='c':self.confirm(self.model.clear)
        elif char in ('+','-','='):self.model.size=(self.model.size+(-1 if char=='-' else 1))%len(SIZES)
        elif char in '12345678' and char:self.choose(int(char)-1)
        elif char=='p':self.colors()
        elif key=='space' and self.root.focus_get() is self.canvas:
            self.pen=not self.pen
            self.model.begin(*self.cursor) if self.pen else self.model.end()
        elif key in ('Up','Down','Left','Right') and self.root.focus_get() is self.canvas:
            dx,dy={'Up':(0,-3),'Down':(0,3),'Left':(-3,0),'Right':(3,0)}[key]
            self.cursor[:]=self.model.point(self.cursor[0]+dx,self.cursor[1]+dy)
            if self.pen:self.model.stroke(*self.cursor)
        elif char=='?':
            self.footer.configure(text='N new · O open · S save · Shift+S as · U/Y undo/redo · E tool · ± size · 1–8 color')
            return 'break'
        else:return None
        self.changed()
        return 'break'

    def close(self):
        if self.closed:return
        self.closed=True
        self.root.after_cancel(self.signal_job)
        if self.frame:self.root.after_cancel(self.frame)
        try:write_state(self.paths.state/'settings.json',{'color':self.model.color,'size':self.model.size})
        except (OSError,ValueError):pass
        self.root.destroy()

    def terminate(self):
        if self.model.dirty:
            try:
                self.model.save(self.paths.documents/f'Recovery-{time.time_ns()}.png')
            except (OSError,ValueError) as error:
                print(f'Sketch recovery save failed: {error}',file=sys.stderr)
        self.close()


def main():
    try:
        root=tk.Tk()
        app=App(root)
    except (tk.TclError,OSError,ValueError) as error:
        print(f'Sketch could not start: {error}',file=sys.stderr)
        return 1
    previous={s:signal.signal(s,lambda *_:app.terminate()) for s in (signal.SIGTERM,signal.SIGINT)}
    try:root.mainloop()
    finally:
        app.close()
        for s,handler in previous.items():signal.signal(s,handler)
    return 0


if __name__=='__main__':sys.exit(main())
