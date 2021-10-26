from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Union

from .const import TRUE, FALSE

TopicDictCallbackType = Callable[[str, Any], bool]


class TopicNode(dict):
    def __init__(self, value: Any = None, sub_topic: Dict[str, TopicNode] = {}):
        super().__init__(sub_topic)
        self.value = value

    def __str__(self):
        topic_child_str = ", ".join(
            "%s: %s" % (key, self[key].__str__()) for key in super().keys()
        )
        return "(%s, {%s})" % (self.value, topic_child_str)

    def __repr__(self):
        return self.__str__()


class TopicDict(TopicNode):
    def __init__(self, include_topics: List = [], exclude_topics: List = []):
        super().__init__()
        self._listeners = list()
        self._include_topics = list()
        self._exclude_topics = list()
        self.add_include_topic(*include_topics)
        self.add_exclude_topic(*exclude_topics)

    @staticmethod
    def _topic_to_lst(topic_path: str) -> list:
        return topic_path.strip("/").split("/")

    @staticmethod
    def get_topic_head(topic: str) -> Union[tuple[str, str], bool]:
        topic = topic.strip("/")
        last_slash_index = topic.rfind("/")

        if last_slash_index == -1:
            return False

        return topic[last_slash_index + 1 :], topic

    def add_include_topic(self, *regex_patterns: List[str]):
        for regex_pattern in regex_patterns:
            self._include_topics.append(re.compile(regex_pattern))

    def add_exclude_topic(self, *regex_patterns: List[str]):
        for regex_pattern in regex_patterns:
            self._exclude_topics.append(re.compile(regex_pattern))

    def add_listener(self, callback: TopicDictCallbackType):
        self._listeners.append(callback)

    def topic_get(self, topic_path: Union[str, list], default=None):

        if not isinstance(topic_path, list):
            topic_path = self._topic_to_lst(topic_path)

        topic_node = self

        for topic_lvl in topic_path:

            if topic_lvl not in topic_node:
                return default

            topic_node = topic_node.get(topic_lvl)

        return topic_node

    def topic_set(self, topic_path: str, value):

        if self._include_topics and not any(
            regex_include.match(topic_path) for regex_include in self._include_topics
        ):
            return False

        if self._exclude_topics and any(
            regex_exclude.match(topic_path) for regex_exclude in self._exclude_topics
        ):
            return False

        if self._listeners and any(
            callback(topic_path, value) for callback in self._listeners
        ):
            return False

        topic_node = self

        for topic_lvl in self._topic_to_lst(topic_path):
            topic_node = topic_node.setdefault(topic_lvl, TopicDict())

        if isinstance(value, TopicDict):
            topic_parent_node, topic_label = self._topic_get_parent(topic_path)
            super(TopicNode, topic_parent_node).__setitem__(topic_label, value)

        else:
            topic_node.value = value

    def _topic_get_parent(self, topic_path: str):

        topic_path_list = self._topic_to_lst(topic_path)
        return self.topic_get(topic_path_list[:-1], False), topic_path_list[-1]

    def topic_del(self, topic_path: str):

        topic_parent_node, topic_label = self._topic_get_parent(topic_path)

        if not topic_parent_node:
            return False

        return topic_parent_node.pop(topic_label, False)

    def __getitem__(self, topic_path):
        return self.topic_get(topic_path)

    def __setitem__(self, topic_path, value):
        self.topic_set(topic_path, value)

    def __delitem__(self, topic_path):
        self.topic_del(topic_path)


def str2bool(val: str):
    return val == TRUE


def bool2str(val: bool):
    return TRUE if val else FALSE
