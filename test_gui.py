# SPDX-License-Identifier: GPL-2.0-or-later
import time
import unittest
from unittest.mock import patch
try:
    from lancer_gtk import LancerApp, Gtk, Gdk, GLib
    HAS_GTK=Gdk.Display.get_default() is not None
except ImportError:
    HAS_GTK=False


def drain(seconds=.25):
    until=time.monotonic()+seconds
    context=GLib.MainContext.default()
    while time.monotonic()<until:
        while context.pending(): context.iteration(False)
        time.sleep(.005)


@unittest.skipUnless(HAS_GTK,'GTK display required; run separately on a desktop')
class PickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=LancerApp(demo=True)
        cls.app.set_application_id('local.lancer.RGB.UITest')
        cls.app.register(None); cls.app.activate(); drain()

    @classmethod
    def tearDownClass(cls):
        cls.app.cancel_preview(); cls.app.window.destroy()

    def setUp(self):
        self.app.cancel_preview(); drain(.05)
        self.app.live.set_active(False)

    def test_hex_and_rgb_stay_in_sync(self):
        self.app.set_color_hex('#FF8040')
        self.assertEqual(self.app.rgb,(255,128,64))
        self.assertEqual([x.get_value_as_int() for x in self.app.channels],[255,128,64])
        self.app.channels[1].set_value(32)
        self.assertEqual(self.app.hex_entry.get_text(),'#FF2040')

    def test_invalid_hex_preserves_color(self):
        previous=self.app.rgb
        self.app.set_color_hex('broken')
        self.assertEqual(self.app.rgb,previous)
        self.assertTrue(self.app.hex_entry.has_css_class('error'))
        self.app.set_color_hex('FFFFFF')
        self.assertFalse(self.app.hex_entry.has_css_class('error'))

    def test_keyboard_picker(self):
        self.app.set_color_hex('804020')
        before=self.app.plane.s
        self.app.plane.key(None,Gdk.KEY_Left,0,Gdk.ModifierType(0))
        self.assertLess(self.app.plane.s,before)
        self.assertEqual(self.app.hex_entry.get_text(),'#'+''.join(f'{v:02X}' for v in self.app.rgb))

    def test_read_preserves_known_brightness(self):
        self.app.last_settings={a:dict(color='FF0000',brightness=50) for a in ('0x71','0x73')}
        data={a:dict(colors=['800000']*8,static=True) for a in ('0x71','0x73')}
        self.app.show_hardware(data)
        self.assertEqual(self.app.rgb,(255,0,0))
        self.assertEqual(self.app.slider.get_value(),50)
        self.assertEqual(self.app.preview_timer,0)

    def test_slider_coalesces_without_saving(self):
        self.app.live.set_active(True)
        with patch.object(self.app,'enqueue') as enqueue:
            for v in (12,21,38,44): self.app.slider.set_value(v)
            drain(.25)
            enqueue.assert_called_once()
            self.assertEqual(enqueue.call_args.args[0],'preview')
            self.assertEqual(enqueue.call_args.args[1][1],44)

    def test_narrow_window_stacks_columns(self):
        self.app.window.set_default_size(440,820); drain()
        self.assertEqual(self.app.columns.get_orientation(),Gtk.Orientation.VERTICAL)
        self.assertFalse(self.app.save_note.get_visible())
        self.app.window.set_default_size(820,770); drain()
        self.assertEqual(self.app.columns.get_orientation(),Gtk.Orientation.HORIZONTAL)

if __name__=='__main__': unittest.main()
