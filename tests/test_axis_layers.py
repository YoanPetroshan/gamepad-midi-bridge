"""Axis settings per layer: slow on the base layer, absolute on another, never a jump."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import Engine, slot_of  # noqa: E402
from mapping import AXIS_IDS, BUTTON_IDS, Profile, default_profile  # noqa: E402


class FakeMidi:
    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)

    def cc(self, control):
        return [m.value for m in self.sent if m.type == "control_change" and m.control == control]


def state(buttons=(), **axes):
    return ("state", tuple(b in buttons for b in BUTTON_IDS), tuple(axes.get(a, 0.0) for a in AXIS_IDS), False)


class AxisLayerTest(unittest.TestCase):
    def setUp(self):
        p = default_profile()
        p.buttons["leftshoulder"].action = "modifier"
        base = p.axes["leftx"]
        base.mode, base.curve, base.deadzone, base.max_speed = "rate", "linear", 0.0, 0.2  # slow
        own = p.ensure_axis_override("leftshoulder", "leftx")
        own.mode = "absolute"  # same CC 10, but the stick position is the value
        self.profile, self.own = p, own
        self.midi = FakeMidi()
        self.eng = Engine(p, self.midi)
        self.t = 0.0
        self.eng.feed(("connected", "Pad", {}), self.t)
        self.eng.feed(state(), self.t)
        self.run_for(0.3)
        self.midi.sent.clear()

    def run_for(self, seconds, dt=0.004):
        end = self.t + seconds
        while self.t < end:
            self.t += dt
            self.eng.step(self.t)

    def feed(self, held=(), seconds=0.05, **axes):
        self.eng.feed(state(held, **axes), self.t)
        self.run_for(seconds)

    def put(self, v):
        """Put the head at v (0..1) for real: it is sent, then forgotten, like a position from before."""
        self.eng.set_axis_value("leftx", v)
        self.run_for(0.05)
        self.midi.sent.clear()

    def sweep(self, held, start, stop, seconds=0.4, steps=40):
        for i in range(1, steps + 1):
            self.feed(held, seconds / steps, leftx=start + (stop - start) * i / steps)
        self.feed(held, 0.1, leftx=stop)  # let the rate limit send the last value

    # ------------------------------------------------------------------ the two behaviours
    def test_base_layer_is_slow_and_the_layer_is_absolute(self):
        self.feed(leftx=1.0, seconds=0.5)  # base: rate 0.2/s → about +0.1
        self.assertAlmostEqual(self.eng.rate_values["leftx"], 0.6, delta=0.03)
        self.feed()  # let go of the stick
        self.put(0.5)
        self.sweep(("leftshoulder",), 0.0, 1.0)  # layer LB: the position is the value
        self.assertEqual(self.midi.cc(10)[-1], 127, "stick fully right = 127 in the absolute layer")

    def test_entering_the_layer_does_not_jump(self):
        self.put(0.9)  # the head is at 114
        self.feed(("leftshoulder",), 0.3)  # LB held, stick in the middle (would be 64)
        self.assertEqual(self.midi.cc(10), [], "absolute stick must not drag the head to the middle")
        self.sweep(("leftshoulder",), 0.0, 0.7)  # not there yet (needs +0.8)
        self.assertEqual(self.midi.cc(10), [])
        self.sweep(("leftshoulder",), 0.7, 1.0, steps=30)  # crosses the kept value: takes over
        sent = self.midi.cc(10)
        self.assertTrue(sent and abs(sent[0] - 114) <= 3, sent[:3])
        self.assertEqual(sent[-1], 127)

    def test_leaving_the_layer_continues_from_where_it_is(self):
        self.put(0.5)
        self.sweep(("leftshoulder",), 0.0, 1.0)  # absolute: 127
        self.midi.sent.clear()
        self.feed((), 0.1, leftx=1.0)  # LB released, stick still full right: base rate, already at the end
        self.feed((), 0.5, leftx=-1.0)  # now slowly down from 127, not from 64
        sent = self.midi.cc(10)
        self.assertTrue(sent and sent[0] >= 120, sent[:3])
        self.assertGreater(sent[-1], 100, "slow: 0.2/s for half a second only takes off ~13")

    # ------------------------------------------------------------------ another parameter per layer
    def test_a_layer_can_drive_another_cc_with_its_own_value(self):
        self.own.cc, self.own.mode = 14, "rate"
        self.eng.mapping_changed("leftx")
        self.put(0.8)  # base CC 10 is at 0.8
        self.feed(("leftshoulder",), 0.5, leftx=1.0)
        self.assertEqual(self.midi.cc(10), [], "the base parameter is left alone")
        first = self.midi.cc(14)[0]
        self.assertTrue(60 <= first <= 70, f"a new CC starts from the middle, not from CC 10's value: {first}")
        self.feed((), 0.2)
        self.assertAlmostEqual(self.eng.rate_values["leftx"], 0.8, delta=0.01, msg="CC 10 kept its value")
        self.assertIn(slot_of(self.own), self.eng.slot_values)

    def test_every_value_is_kept_per_parameter(self):
        self.own.cc, self.own.mode = 14, "rate"
        self.eng.mapping_changed("leftx")
        self.feed(("leftshoulder",), 0.5, leftx=1.0)
        in_layer = self.eng.slot_values[(1, 14, False)]
        self.feed((), 0.3)
        self.feed(("leftshoulder",), 0.1)  # back into the layer
        self.assertAlmostEqual(self.eng.rate_values["leftx"], in_layer, delta=0.001)

    # ------------------------------------------------------------------ inheritance and editing live
    def test_a_deeper_layer_inherits_until_it_has_its_own(self):
        self.profile.buttons["dpup"].action = "modifier"
        self.feed(("leftshoulder", "dpup"), 0.05)
        self.assertEqual(self.eng.current_layer, "leftshoulder+dpup")
        self.assertIs(self.eng._eff["leftx"], self.own)
        deeper = self.profile.ensure_axis_override("leftshoulder+dpup", "leftx")
        self.eng.mapping_changed("leftx")
        self.assertIs(self.eng._eff["leftx"], deeper)

    def test_removing_the_override_while_inside_does_not_jump(self):
        self.put(0.7)
        self.feed(("leftshoulder",), 0.1)
        self.midi.sent.clear()
        self.profile.remove_axis_override("leftshoulder", "leftx")
        self.eng.mapping_changed("leftx")
        self.feed(("leftshoulder",), 0.3)
        self.assertEqual(self.midi.cc(10), [])
        self.assertIs(self.eng._eff["leftx"], self.profile.axes["leftx"])

    def test_other_axes_are_untouched_by_the_layer(self):
        self.feed(("leftshoulder",), 0.1)
        self.assertIs(self.eng._eff["lefty"], self.profile.axes["lefty"])
        self.assertIs(self.eng._eff["righttrigger"], self.profile.axes["righttrigger"])

    # ------------------------------------------------------------------ storage
    def test_profile_round_trip_keeps_the_override(self):
        q = Profile.from_json(self.profile.to_json())
        self.assertEqual(q.axis_layers["leftshoulder"]["leftx"].mode, "absolute")
        self.assertEqual(q.axes["leftx"].mode, "rate")

    def test_values_saved_per_axis_by_older_versions_are_still_understood(self):
        eng = Engine(default_profile(), FakeMidi(), rate_values={"leftx": 0.8, "lefty": 0.3})
        self.assertAlmostEqual(eng.rate_values["leftx"], 0.8)
        self.assertAlmostEqual(eng.rate_values["lefty"], 0.3)
        eng2 = Engine(default_profile(), FakeMidi(), slot_values={(1, 10, False): 0.25})
        self.assertAlmostEqual(eng2.rate_values["leftx"], 0.25)

    def test_clear_layer_forgets_the_axis_settings_too(self):
        self.profile.clear_layer("leftshoulder")
        self.assertNotIn("leftshoulder", self.profile.axis_layers)
        self.assertIsNone(self.profile.axis_source("leftshoulder", "leftx"))

    def test_usage_lists_the_layer_cc(self):
        self.own.cc = 14
        who = self.profile.usage("cc", 1)
        self.assertTrue(any("Left stick X" in w and "LB" in w for w in who[14]), who.get(14))


if __name__ == "__main__":
    unittest.main()
