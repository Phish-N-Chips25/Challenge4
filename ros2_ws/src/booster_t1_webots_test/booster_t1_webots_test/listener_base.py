from __future__ import annotations

from .message_formatters import topic_candidates


class MultiTopicCounter:
    def __init__(self):
        self.count_by_topic: dict[str, int] = {}

    def next_count(self, topic: str) -> int:
        count = self.count_by_topic.get(topic, 0) + 1
        self.count_by_topic[topic] = count
        return count


def create_subscriptions(node, msg_type, base_name: str, callback_factory, robot_name: str = "booster_t1"):
    subscriptions = []
    for topic in topic_candidates(base_name, robot_name):
        subscriptions.append(node.create_subscription(msg_type, topic, callback_factory(topic), 10))
        node.get_logger().info(f"Listening on {topic}")
    return subscriptions
