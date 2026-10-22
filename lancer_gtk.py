#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Native lighting controls. Launch and selection never write hardware."""
import colorsys
import os
import json
from pathlib import Path
import subprocess
import threading
# Small Cairo-drawn controls do not need GPU rendering; avoid driver text artifacts.
os.environ.setdefault('GSK_RENDERER', 'cairo')
import gi

gi.require_version('Gtk','4.0')
gi.require_version('Adw','1')
from gi.repository import Gtk, Gdk, Gio, GLib, Adw
from color_widgets import ColorPlane, MemoryPreview
import lancer_rgb

ROOT=Path(__file__).resolve().parent
HELPER=Path('/usr/local/bin/lancer-rgb-control')
STATE=Path('/var/lib/lancer-rgb/settings.json')


def label(text,css=None):
    widget=Gtk.Label(label=text,xalign=0)
    if css: widget.add_css_class(css)
    return widget


def column(spacing=12):
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=spacing)


def margins(widget,size):
    for side in ('top','bottom','start','end'): getattr(widget,'set_margin_'+side)(size)


class LancerApp(Adw.Application):
    def __init__(self,demo=False):
        settings=Gtk.Settings.get_default()
        if settings: settings.set_property('gtk-application-prefer-dark-theme',False)
        super().__init__(application_id='local.lancer.RGB',flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.demo=demo
        self.bus=None; self.busy=False; self.initializing=True
        self.pending=None; self.preview_timer=0; self.revision=0
        self.rgb=(65,214,195); self.hardware={}; self.syncing=False
        self.target_index=0
        self.last_settings={}

    def do_activate(self):
        if self.get_active_window(): self.get_active_window().present(); return
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
        css=Gtk.CssProvider(); css.load_from_path(str(ROOT/'style.css'))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(),css,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(str(ROOT/'icons'))
        Gtk.Window.set_default_icon_name('local.lancer.RGB')
        self.window=Adw.ApplicationWindow(application=self,title='Lancer RGB')
        self.window.set_default_size(820,770)
        self.window.set_size_request(420,550)
        toolbar=Adw.ToolbarView(); self.window.set_content(toolbar)
        header=Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title='Lancer RGB',subtitle='Memory lighting'))
        self.read_button=Gtk.Button(icon_name='view-refresh-symbolic',tooltip_text='Read current colors from RAM')
        self.read_button.connect('clicked',lambda _:self.read_ram()); header.pack_start(self.read_button)
        menu=Gio.Menu(); menu.append('About Lancer RGB','app.about')
        about=Gio.SimpleAction.new('about',None); about.connect('activate',self.about); self.add_action(about)
        header.pack_end(Gtk.MenuButton(icon_name='open-menu-symbolic',menu_model=menu,tooltip_text='Main menu'))
        toolbar.add_top_bar(header)
        scroller=Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,vexpand=True)
        toolbar.set_content(scroller)
        content=column(22); margins(content,24); scroller.set_child(content)
        self.columns=Gtk.Box(spacing=20,orientation=Gtk.Orientation.HORIZONTAL)
        content.append(self.columns)
        self.left=column(16); self.left.set_size_request(220,-1)
        self.left.set_hexpand(False); self.columns.append(self.left)
        self.right=column(16); self.right.set_hexpand(True); self.right.set_size_request(310,-1)
        self.columns.append(self.right)
        breakpoint=Adw.Breakpoint.new(Adw.BreakpointCondition.parse('max-width: 720px'))
        breakpoint.add_setter(self.columns,'orientation',Gtk.Orientation.VERTICAL)
        self.window.add_breakpoint(breakpoint)
        device=column(10); device.add_css_class('surface'); margins(device,0); self.left.append(device)
        device.append(label('Lancer Blade','title-2'))
        device.append(label('2 modules · 16 LEDs','dim-label'))
        self.memory=MemoryPreview(); device.append(self.memory)
        self.source_label=label('Waiting for hardware…','dim-label'); device.append(self.source_label)
        self.module_labels=self.memory.labels
        targetcard=column(16); margins(targetcard,4); self.left.append(targetcard)
        self.targets=[]; segment=Gtk.Box(homogeneous=True); segment.add_css_class('linked')
        for i,name in enumerate(('Both','Module 1','Module 2')):
            button=Gtk.ToggleButton(label=name)
            if self.targets: button.set_group(self.targets[0])
            button.connect('toggled',self.target_changed,i)
            segment.append(button); self.targets.append(button)
        self.targets[0].set_active(True); targetcard.append(segment)
        live_row=Gtk.Box(spacing=12)
        desc=column(3); desc.append(label('Live preview','heading')); desc.append(label('Update LEDs as you edit','dim-label'))
        live_row.append(desc)
        self.live=Gtk.Switch(active=True,halign=Gtk.Align.END,valign=Gtk.Align.CENTER,hexpand=True)
        self.live.connect('notify::active',self.live_changed); live_row.append(self.live); targetcard.append(live_row)
        picker=column(10); picker.add_css_class('surface'); self.right.append(picker)
        picker.append(label('Pick a color','title-2'))
        self.plane=ColorPlane(); self.hue=ColorPlane(hue_only=True)
        self.plane.connect('color-changed',self.plane_changed); self.hue.connect('color-changed',self.hue_changed)
        picker.append(self.plane); picker.append(self.hue)
        swatches=Gtk.Box(spacing=7,homogeneous=True)
        for name,color in [('Ice','64CFFF'),('Mint','41D6C3'),('Lime','B4E66E'),('Amber','FFBA66'),('Coral','FF747B'),('Lilac','B49AFF'),('White','FFFFFF')]:
            button=Gtk.Button(tooltip_text=name+' · #'+color); button.add_css_class('swatch')
            dot=Gtk.DrawingArea(content_height=24,content_width=24)
            rgb=tuple(int(color[i:i+2],16)/255 for i in (0,2,4))
            def draw(w,cr,ww,hh,rgb=rgb):
                cr.set_source_rgb(*rgb); cr.arc(ww/2,hh/2,9,0,6.283); cr.fill()
            dot.set_draw_func(draw); button.set_child(dot)
            button.connect('clicked',lambda _,value=color:self.set_color_hex(value)); swatches.append(button)
        picker.append(swatches)
        inputs=Gtk.Box(spacing=12)
        hexbox=column(5); hexbox.append(label('Hex','field-label'))
        self.hex_entry=Gtk.Entry(text='#41D6C3',width_chars=9,max_length=7,hexpand=True)
        self.hex_entry.set_tooltip_text('Enter #RRGGBB and press Enter')
        self.hex_entry.update_property([Gtk.AccessibleProperty.LABEL],['Hex color'])
        self.hex_entry.connect('activate',self.hex_changed)
        hexbox.append(self.hex_entry); inputs.append(hexbox)
        self.channels=[]
        rgbrow=Gtk.Box(spacing=10,homogeneous=True)
        for name in ('R','G','B'):
            channel=column(5); channel.append(label(name,'field-label'))
            spin=Gtk.SpinButton.new_with_range(0,255,1); spin.set_width_chars(3); spin.set_hexpand(True)
            spin.update_property([Gtk.AccessibleProperty.LABEL],[{'R':'Red','G':'Green','B':'Blue'}[name]])
            spin.connect('value-changed',self.rgb_changed); channel.append(spin); rgbrow.append(channel); self.channels.append(spin)
        picker.append(inputs)
        advanced=Gtk.Expander(label='RGB values')
        advanced.set_child(rgbrow); picker.append(advanced)
        brightness=column(8); margins(brightness,4); self.right.append(brightness)
        row=Gtk.Box(); row.append(label('Brightness','heading'))
        self.percent=Gtk.Label(label='100%',hexpand=True,xalign=1); self.percent.add_css_class('monospace'); row.append(self.percent); brightness.append(row)
        self.slider=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,0,100,1)
        self.slider.set_draw_value(False); self.slider.set_value(100)
        self.slider.update_property([Gtk.AccessibleProperty.LABEL],['Brightness'])
        self.slider.connect('value-changed',self.brightness_changed); brightness.append(self.slider)
        self.status=label('Connecting…','dim-label'); self.status.set_wrap(True); content.append(self.status)
        bottom=Gtk.Box(spacing=12); margins(bottom,16); bottom.add_css_class('bottom-bar')
        self.off=Gtk.Button(label='Turn off'); self.off.connect('clicked',lambda _:self.write(True)); bottom.append(self.off)
        self.save_note=Gtk.Label(label='Live changes are not saved',hexpand=True,xalign=0); self.save_note.add_css_class('dim-label'); bottom.append(self.save_note)
        self.apply_button=Gtk.Button(label='Save for startup'); self.apply_button.add_css_class('suggested-action'); self.apply_button.set_tooltip_text('Apply this color and restore it on future boots')
        self.apply_button.connect('clicked',lambda _:self.write()); bottom.append(self.apply_button); toolbar.add_bottom_bar(bottom)
        small=Adw.Breakpoint.new(Adw.BreakpointCondition.parse('max-width: 600px'))
        small.add_setter(self.save_note,'visible',False)
        small.add_setter(self.columns,'orientation',Gtk.Orientation.VERTICAL)
        self.window.add_breakpoint(small)
        self.set_color(self.rgb,notify=False)
        self.initializing=False
        try:
            if self.demo: self.bus=6
            else:
                buses=[b['bus'] for b in lancer_rgb.inventory() if b['name'].startswith('SMBus I801 adapter')]
                if len(buses)!=1: raise RuntimeError('Could not find a unique Intel I801 adapter.')
                self.bus=buses[0]; lancer_rgb.check_host(self.bus)
                if not HELPER.exists(): raise RuntimeError('Install the lighting helper to connect to your memory.')
        except (RuntimeError,OSError) as exc:
            self.bus=None; self.status.set_text(str(exc)); self.live.set_active(False)
            for w in (self.apply_button,self.off,self.read_button): w.set_sensitive(False)
        self.window.connect('close-request',self.closing)
        self.window.present()
        self.read_button.grab_focus()
        if self.bus is not None: GLib.idle_add(self.read_ram)

    def about(self,*_):
        Adw.AboutDialog(application_name='Lancer RGB',application_icon='local.lancer.RGB',
            version='0.1.0',developer_name='Lancer RGB contributors',license_type=Gtk.License.GPL_2_0,
            comments='A small native controller for XPG Lancer Blade RGB memory.').present(self.window)

    def set_color_hex(self,value):
        try: rgb=lancer_rgb.rgb(value)
        except Exception:
            self.hex_entry.add_css_class('error'); self.status.set_text('Use six hex digits, such as #41D6C3.'); return
        self.hex_entry.remove_css_class('error'); self.set_color(rgb)

    def hex_changed(self,entry): self.set_color_hex(entry.get_text().strip())

    def rgb_changed(self,*_):
        if not self.syncing: self.set_color(tuple(spin.get_value_as_int() for spin in self.channels))

    def plane_changed(self,plane):
        self.set_color(tuple(round(v*255) for v in colorsys.hsv_to_rgb(plane.h,plane.s,plane.v)),preserve_hsv=True)

    def hue_changed(self,hue):
        self.plane.h=hue.h
        self.set_color(tuple(round(v*255) for v in colorsys.hsv_to_rgb(hue.h,self.plane.s,self.plane.v)),preserve_hsv=True)

    def set_color(self,rgb,notify=True,preserve_hsv=False):
        self.rgb=rgb; self.syncing=True
        self.hex_entry.set_text('#'+''.join(f'{v:02X}' for v in rgb)); self.hex_entry.remove_css_class('error')
        for spin,v in zip(self.channels,rgb): spin.set_value(v)
        if preserve_hsv: h,s,v=self.plane.h,self.plane.s,self.plane.v
        else:
            h,s,v=colorsys.rgb_to_hsv(*(c/255 for c in rgb))
            if s==0: h=self.plane.h
        self.plane.set_hsv(h,s,v); self.hue.set_hsv(h,s,v)
        self.syncing=False
        if notify: self.edited()

    def brightness_changed(self,*_):
        self.percent.set_text(f'{round(self.slider.get_value())}%')
        if not self.syncing: self.edited()

    def selection(self,off=False):
        return ('000000' if off else ''.join(f'{c:02X}' for c in self.rgb),round(self.slider.get_value()),['both','0x71','0x73'][self.target_index])

    def edited(self):
        if self.initializing: return
        self.revision+=1
        color,brightness,address=self.selection()
        effective=''.join(f'{(v*brightness+50)//100:02X}' for v in self.rgb)
        for i in range(2):
            if self.target_index in (0,i+1): self.memory.colors[i]=[effective]*8
        self.memory.queue_draw(); self.source_label.set_text('Preview'); self.save_note.set_text('Not saved for startup')
        if self.bus is not None and self.live.get_active() and not self.preview_timer:
            self.preview_timer=GLib.timeout_add(180,self.preview)

    def preview(self):
        self.preview_timer=0
        if self.live.get_active(): self.enqueue('preview',self.selection())
        return False

    def cancel_preview(self):
        if self.preview_timer: GLib.source_remove(self.preview_timer); self.preview_timer=0
        if self.pending and self.pending[0]=='preview': self.pending=None

    def live_changed(self,*_):
        if not self.live.get_active(): self.cancel_preview()

    def target_changed(self,button,index):
        if not button.get_active(): return
        self.target_index=index
        if self.initializing: return
        self.revision+=1; self.cancel_preview(); self.read_ram()

    def closing(self,*_):
        if self.busy: return True
        self.cancel_preview(); return False

    def write(self,off=False):
        self.cancel_preview(); self.enqueue('set',self.selection(off))

    def read_ram(self):
        self.cancel_preview(); self.enqueue('read',None); return False

    def enqueue(self,action,selection):
        if self.bus is None: return
        if self.busy: self.pending=(action,selection); return
        self.busy=True; revision=self.revision
        for w in (self.apply_button,self.off,self.read_button): w.set_sensitive(False)
        self.status.set_text('Reading your memory…' if action=='read' else 'Updating lighting…')
        command=['pkexec','--disable-internal-agent',str(HELPER),action]
        if selection:
            color,brightness,address=selection
            command+=['--color',color,'--brightness',str(brightness),'--address',address]
        def run():
            data=None; error=None
            try:
                if self.demo:
                    if action=='read': data={a:dict(colors=['41D6C3']*8,static=True,mode=1,direct=0) for a in ('0x71','0x73')}
                else:
                    result=subprocess.run(command,capture_output=True,text=True,timeout=15)
                    if result.returncode: error=(result.stderr.strip() or f'Lighting helper exited with code {result.returncode}.')[-900:]
                    elif action=='read': data=json.loads(result.stdout)
            except (OSError,ValueError,subprocess.TimeoutExpired) as exc: error=str(exc)
            GLib.idle_add(self.finished,action,selection,data,error,revision)
        threading.Thread(target=run,daemon=True).start()

    def show_hardware(self,data):
        self.hardware=data
        try:
            saved=json.loads(STATE.read_text())
        except (OSError,ValueError): saved={}
        for i,address in enumerate(('0x71','0x73')):
            item=data[address]
            if item['static']:
                self.memory.colors[i]=item['colors']
                self.module_labels[i].set_text('#'+item['colors'][0] if len(set(item['colors']))==1 else 'Multiple colors')
            else:
                self.memory.colors[i]=['222830']*8; self.module_labels[i].set_text('Animated mode')
        self.memory.queue_draw(); self.source_label.set_text('Read from RAM · just now')
        values=list(data.values()) if self.target_index==0 else [data[['0x71','0x73'][self.target_index-1]]]
        colors=[c for value in values for c in value['colors']]
        if all(v['static'] for v in values) and len(set(colors))==1:
            addresses=['0x71','0x73'] if self.target_index==0 else [['0x71','0x73'][self.target_index-1]]
            candidates=[self.last_settings.get(a) or saved.get(a) for a in addresses]
            candidate=candidates[0]
            picked=lancer_rgb.rgb(colors[0]); brightness=100
            if candidate and all(c==candidate for c in candidates):
                try:
                    base=lancer_rgb.rgb(candidate['color']); level=candidate['brightness']
                    effective=''.join(f'{(v*level+50)//100:02X}' for v in base)
                    if type(level) is int and 0<=level<=100 and effective==colors[0]:
                        picked=base; brightness=level
                except (ValueError,TypeError,KeyError): pass
            self.initializing=True; self.syncing=True
            self.slider.set_value(brightness); self.set_color(picked,notify=False)
            self.syncing=False; self.initializing=False
        if not all(v['static'] for v in values):
            self.status.set_text('Animated mode is active. Choose a color to switch to static lighting.')
        elif len(set(colors))>1:
            self.status.set_text('The selected LEDs have different colors. Choosing a color will replace them.')
        else:
            self.status.set_text('Colors read from RAM.')
        self.status.set_tooltip_text('Readback contains effective RGB. Original brightness is kept when it matches known settings; otherwise the effective color is shown at 100%.')

    def finished(self,action,selection,data,error,revision):
        self.busy=False
        for w in (self.apply_button,self.off,self.read_button): w.set_sensitive(True)
        if error:
            self.pending=None; self.live.set_active(False)
            self.status.set_text('Live preview stopped. '+error); return False
        if action=='read':
            if revision==self.revision and self.pending is None: self.show_hardware(data)
        else:
            color,brightness,address=selection
            effective=''.join(f'{(v*brightness+50)//100:02X}' for v in lancer_rgb.rgb(color))
            for i,a in enumerate(('0x71','0x73')):
                if address in ('both',a):
                    self.last_settings[a]={'color':color,'brightness':brightness}
                    self.module_labels[i].set_text('#'+effective)
                    if revision==self.revision: self.memory.colors[i]=[effective]*8
            self.memory.queue_draw(); self.source_label.set_text('Last applied · refresh to read RAM')
            self.status.set_text('Color saved. It will be restored at startup.' if action=='set' else 'Live preview active.')
            self.save_note.set_text('Saved for startup' if action=='set' and revision==self.revision else 'Not saved for startup')
        if self.pending:
            action,selection=self.pending; self.pending=None; self.enqueue(action,selection)
        return False

if __name__=='__main__':
    import sys
    demo='--demo' in sys.argv
    raise SystemExit(LancerApp(demo=demo).run([sys.argv[0]]))
