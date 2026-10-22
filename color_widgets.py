# SPDX-License-Identifier: GPL-2.0-or-later
"""Cairo color controls; no hardware access."""
import colorsys
import math
import cairo
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, GObject


def clamp(value):
    return max(0.0, min(1.0, value))


def rounded(cr, x, y, width, height, radius):
    radius=min(radius,width/2,height/2)
    cr.new_sub_path()
    for cx,cy,start in [(x+width-radius,y+radius,-90),(x+width-radius,y+height-radius,0),
                        (x+radius,y+height-radius,90),(x+radius,y+radius,180)]:
        cr.arc(cx,cy,radius,math.radians(start),math.radians(start+90))
    cr.close_path()


class ColorPlane(Gtk.DrawingArea):
    __gsignals__={'color-changed':(GObject.SignalFlags.RUN_FIRST,None,())}

    def __init__(self, hue_only=False):
        super().__init__()
        self.hue_only=hue_only
        self.h,self.s,self.v=0.5,0.7,1.0
        self.set_content_height(30 if hue_only else 230)
        self.set_hexpand(True); self.set_focusable(True)
        self.set_cursor_from_name('crosshair' if not hue_only else 'pointer')
        self.set_tooltip_text('Hue: left/right arrow keys' if hue_only else 'Saturation and value: arrow keys; Shift for larger steps')
        self.update_property([Gtk.AccessibleProperty.LABEL],['Hue' if hue_only else 'Saturation and value'])
        self.set_draw_func(self.draw)
        drag=Gtk.GestureDrag()
        drag.connect('drag-begin',self.begin)
        drag.connect('drag-update',self.drag)
        self.add_controller(drag)
        keys=Gtk.EventControllerKey(); keys.connect('key-pressed',self.key)
        self.add_controller(keys)

    def set_hsv(self,h,s,v):
        self.h,self.s,self.v=h,s,v; self.queue_draw()

    def begin(self,gesture,x,y):
        self.start=(x,y); self.grab_focus(); self.pick(x,y)

    def drag(self,gesture,x,y):
        self.pick(self.start[0]+x,self.start[1]+y)

    def pick(self,x,y):
        if self.hue_only: self.h=clamp((x-7)/max(1,self.get_width()-14))
        else:
            self.s=clamp((x-7)/max(1,self.get_width()-14))
            self.v=1-clamp((y-7)/max(1,self.get_height()-14))
        self.queue_draw(); self.emit('color-changed')

    def key(self,controller,keyval,keycode,state):
        step=0.05 if state & Gdk.ModifierType.SHIFT_MASK else 0.01
        if keyval not in (Gdk.KEY_Left,Gdk.KEY_Right,Gdk.KEY_Up,Gdk.KEY_Down): return False
        if self.hue_only:
            self.h=clamp(self.h+step*(1 if keyval in (Gdk.KEY_Right,Gdk.KEY_Up) else -1))
        elif keyval in (Gdk.KEY_Left,Gdk.KEY_Right):
            self.s=clamp(self.s+step*(1 if keyval==Gdk.KEY_Right else -1))
        else: self.v=clamp(self.v+step*(1 if keyval==Gdk.KEY_Up else -1))
        self.queue_draw(); self.emit('color-changed'); return True

    def draw(self,widget,cr,w,h):
        x,y,ww,hh=7,7,w-14,h-14
        cr.save(); rounded(cr,x,y,ww,hh,hh/2 if self.hue_only else 12); cr.clip()
        if self.hue_only:
            grad=cairo.LinearGradient(x,0,x+ww,0)
            for i in range(7): grad.add_color_stop_rgb(i/6,*colorsys.hsv_to_rgb(i/6,1,1))
            cr.set_source(grad); cr.paint()
            cx,cy=x+self.h*ww,h/2
        else:
            cr.set_source_rgb(*colorsys.hsv_to_rgb(self.h,1,1)); cr.paint()
            grad=cairo.LinearGradient(x,0,x+ww,0)
            grad.add_color_stop_rgba(0,1,1,1,1); grad.add_color_stop_rgba(1,1,1,1,0)
            cr.set_source(grad); cr.paint()
            grad=cairo.LinearGradient(0,y,0,y+hh)
            grad.add_color_stop_rgba(0,0,0,0,0); grad.add_color_stop_rgba(1,0,0,0,1)
            cr.set_source(grad); cr.paint()
            cx,cy=x+self.s*ww,y+(1-self.v)*hh
        cr.restore()
        cr.arc(cx,cy,7,0,2*math.pi); cr.set_source_rgba(0,0,0,0.6); cr.set_line_width(5); cr.stroke()
        cr.arc(cx,cy,7,0,2*math.pi); cr.set_source_rgb(1,1,1); cr.set_line_width(2.5); cr.stroke()
        if self.has_focus():
            rounded(cr,1,1,w-2,h-2,14); cr.set_source_rgba(0.7,0.85,1,0.9); cr.set_line_width(2); cr.stroke()


class MemoryPreview(Gtk.Box):
    """Lancer Blade side silhouettes with the eight hardware colors in the diffuser."""
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL,spacing=18)
        self.colors=[['222830']*8,['222830']*8]
        self.labels=[]; self.strips=[]
        self.set_margin_top(12); self.set_margin_bottom(10)
        for index in range(2):
            group=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8)
            row=Gtk.Box(spacing=8)
            row.append(Gtk.Label(label=f'Module {index+1}',xalign=0))
            value=Gtk.Label(label='—',hexpand=True,xalign=1)
            value.add_css_class('monospace'); row.append(value); self.labels.append(value)
            group.append(row)
            strip=Gtk.DrawingArea(content_height=90,hexpand=True)
            strip.set_draw_func(self.draw,index)
            strip.update_property([Gtk.AccessibleProperty.LABEL],[f'Module {index+1}: eight LED colors'])
            group.append(strip); self.strips.append(strip); self.append(group)

    def queue_draw(self):
        for strip in self.strips: strip.queue_draw()

    def draw(self,widget,cr,w,h,index):
        # Draw in module coordinates; keep the physical proportions at every size.
        scale=min((w-4)/600,(h-4)/166)
        if scale<=0: return
        cr.save(); cr.translate((w-600*scale)/2,(h-166*scale)/2); cr.scale(scale,scale)
        def polygon(points,color):
            cr.move_to(*points[0])
            for point in points[1:]: cr.line_to(*point)
            cr.close_path(); cr.set_source_rgba(*color); cr.fill()
        # PCB and the keyed gold contact edge.
        rounded(cr,18,27,564,129,3); cr.set_source_rgb(.045,.055,.049); cr.fill()
        for contact in range(70):
            x=24+contact*7.9
            if 280<x<300: continue
            cr.rectangle(x,145,5.2,13)
            cr.set_source_rgb(.56,.43,.22); cr.fill()
            cr.rectangle(x+.6,145,3.8,9); cr.set_source_rgb(.76,.63,.36); cr.fill()
        # Continuous frosted diffuser. Color stops correspond to the eight LEDs.
        cr.move_to(11,12); cr.line_to(578,12); cr.line_to(590,24)
        cr.line_to(590,42); cr.line_to(9,42); cr.line_to(9,18); cr.close_path()
        cr.save(); cr.clip()
        light=cairo.LinearGradient(12,0,588,0)
        colors=[tuple(int(color[i:i+2],16)/255 for i in (0,2,4)) for color in self.colors[index]]
        light.add_color_stop_rgb(0,*colors[0])
        for led,color in enumerate(colors): light.add_color_stop_rgb((led+.5)/8,*color)
        light.add_color_stop_rgb(1,*colors[-1]); cr.set_source(light); cr.paint()
        sheen=cairo.LinearGradient(0,12,0,42)
        sheen.add_color_stop_rgba(0,1,1,1,.32); sheen.add_color_stop_rgba(.45,1,1,1,.08); sheen.add_color_stop_rgba(1,0,0,0,.18)
        cr.set_source(sheen); cr.paint(); cr.restore()
        # Black aluminium spreader: bevel, broad face and the Blade's diagonal ribs.
        polygon([(8,35),(591,35),(591,132),(578,146),(20,146),(8,135)],(.055,.06,.068,1))
        cr.save()
        cr.move_to(13,39); cr.line_to(586,39); cr.line_to(586,128)
        cr.line_to(572,140); cr.line_to(22,140); cr.line_to(13,131); cr.close_path(); cr.clip()
        metal=cairo.LinearGradient(0,35,0,143)
        metal.add_color_stop_rgb(0,.20,.21,.225); metal.add_color_stop_rgb(.4,.12,.128,.14); metal.add_color_stop_rgb(1,.075,.08,.09)
        cr.set_source(metal); cr.paint()
        for rib in range(9):
            x=9+rib*22
            polygon([(x,54),(x+91,143),(x+100,143),(x+9,54)],(.025,.029,.035,1))
            cr.move_to(x+10,54); cr.line_to(x+101,142)
            cr.set_source_rgba(.48,.50,.53,.32); cr.set_line_width(1.5); cr.stroke()
        polygon([(13,40),(585,40),(585,121),(327,121),(244,40)],(.15,.16,.175,1))
        # Recessed diagonal boundary leaves the machined ridges exposed below.
        cr.move_to(13,43); cr.line_to(245,43); cr.line_to(333,131); cr.line_to(582,131)
        cr.set_source_rgba(.49,.51,.54,.33); cr.set_line_width(2); cr.stroke()
        cr.move_to(15,47); cr.line_to(241,47); cr.line_to(329,135); cr.line_to(582,135)
        cr.set_source_rgba(0,0,0,.5); cr.set_line_width(5); cr.stroke()
        cr.restore()
        # Side branding, with the DDR generation directly beneath the wordmark.
        cr.select_font_face('DejaVu Sans',cairo.FONT_SLANT_OBLIQUE,cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(38); cr.set_source_rgb(.85,.86,.87)
        cr.move_to(449,91); cr.show_text('XPG')
        cr.select_font_face('DejaVu Sans',cairo.FONT_SLANT_NORMAL,cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(18); cr.move_to(472,115); cr.show_text('DDR5')
        cr.move_to(14,34); cr.line_to(585,34); cr.set_source_rgba(.72,.74,.77,.45); cr.set_line_width(2); cr.stroke()
        cr.restore()
