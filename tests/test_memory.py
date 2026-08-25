import unittest

from casper import memory


class PendingMemoryTests(unittest.TestCase):
    def test_content_learning_checkpoint_survives_normal_user_pause(self):
        self.assertEqual(
            memory._pending_ttl_minutes("content_learning_continue"),
            24 * 60,
        )

    def test_unrelated_device_approval_keeps_short_expiry(self):
        self.assertEqual(
            memory._pending_ttl_minutes("device_action_approval"),
            15,
        )


if __name__ == "__main__":
    unittest.main()
