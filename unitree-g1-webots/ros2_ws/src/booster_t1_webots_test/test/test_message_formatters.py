import unittest

from booster_t1_webots_test.message_formatters import (
    first_items,
    format_imu,
    format_joint_state,
    topic_candidates,
)


class FakeJointState:
    name = ["hip", "knee", "ankle", "shoulder", "elbow", "wrist"]
    position = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]


class FakeVector:
    x = 1.0
    y = 2.0
    z = 3.0


class FakeOrientation:
    x = 0.0
    y = 0.0
    z = 0.0
    w = 1.0


class FakeImu:
    orientation = FakeOrientation()
    angular_velocity = FakeVector()
    linear_acceleration = FakeVector()


class MessageFormatterTest(unittest.TestCase):
    def test_first_items_limits_sequences(self):
        self.assertEqual(first_items([1, 2, 3, 4, 5, 6], 3), [1, 2, 3])

    def test_topic_candidates_prefers_robot_namespace(self):
        self.assertEqual(
            topic_candidates("joint_states", "booster_t1"),
            ["/booster_t1/joint_states", "/joint_states"],
        )

    def test_format_joint_state_summarizes_first_five_entries(self):
        summary = format_joint_state(FakeJointState(), count=7)

        self.assertIn("message #7", summary)
        self.assertIn("joint_count=6", summary)
        self.assertIn("hip", summary)
        self.assertNotIn("wrist", summary)

    def test_format_imu_includes_orientation_velocity_and_acceleration(self):
        summary = format_imu(FakeImu(), count=2)

        self.assertIn("message #2", summary)
        self.assertIn("orientation=(0.000, 0.000, 0.000, 1.000)", summary)
        self.assertIn("angular_velocity=(1.000, 2.000, 3.000)", summary)
        self.assertIn("linear_acceleration=(1.000, 2.000, 3.000)", summary)


if __name__ == "__main__":
    unittest.main()
