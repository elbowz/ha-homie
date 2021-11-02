from __future__ import annotations

import re
from typing import Any, Callable, Union

TopicDictCallbackType = Callable[[str, Any], bool]


class TopicNode(dict):
    def __init__(self, value: Any = None, sub_topic: dict[str, TopicNode] = {}):
        super().__init__(sub_topic)
        self._value = value

    def __str__(self):
        topic_child_str = ", ".join(
            "%s: %s" % (key, self.get(key, return_value=False).__str__())
            for key in super().keys()
        )
        return "(%s, {%s})" % (self._value, topic_child_str)

    def __repr__(self):
        return self.__str__()

    def dict_value(self):
        return {k: v.value for k, v in self.items()}

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, value):
        self._value = value


# TODO: swap super(TopicNode, self) with TopicNode.method(self, )
class TopicDict(TopicNode):
    def __init__(self, include_topics: list[str] = [], exclude_topics: list[str] = []):
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
    def topic_get_head(topic: str) -> Union[tuple[str, str], bool]:
        topic = topic.strip("/")
        last_slash_index = topic.rfind("/")

        if last_slash_index == -1:
            return False

        return topic[last_slash_index + 1 :], topic

    def add_include_topic(self, *regex_patterns: list[str]):
        for regex_pattern in regex_patterns:
            self._include_topics.append(re.compile(regex_pattern))

    def add_exclude_topic(self, *regex_patterns: list[str]):
        for regex_pattern in regex_patterns:
            self._exclude_topics.append(re.compile(regex_pattern))

    def add_listener(self, callback: TopicDictCallbackType):
        self._listeners.append(callback)

    def _get_parent_by_topic(self, topic_path: str):

        topic_path_list = self._topic_to_lst(topic_path)
        return self.get(topic_path_list[:-1], return_value=False), topic_path_list[-1]

    def get(
        self,
        topic_path: Union[str, list],
        default: Any = None,
        return_value: bool = True,
    ) -> Union[Any, TopicDict]:

        if not isinstance(topic_path, list):
            topic_path = self._topic_to_lst(topic_path)

        topic_node = self

        for topic_lvl in topic_path:

            if topic_lvl not in topic_node:
                return default

            topic_node = super(TopicDict, topic_node).__getitem__(topic_lvl)

        return topic_node.value if return_value else topic_node

    def get_obj(
        self, topic_path: Union[str, list], default: TopicNode = TopicNode(None)
    ):
        return self.get(topic_path, default, return_value=False)

    def set(self, topic_path: str, value: Any, force: bool = False):

        if not force:
            if self._include_topics and not any(
                regex_include.search(topic_path)
                for regex_include in self._include_topics
            ):
                return False

            if self._exclude_topics and any(
                regex_exclude.search(topic_path)
                for regex_exclude in self._exclude_topics
            ):
                return False

        topic_node = self

        for topic_lvl in self._topic_to_lst(topic_path):
            topic_node = topic_node.setdefault(topic_lvl, TopicDict())

        if isinstance(value, TopicDict):
            topic_parent_node, topic_label = self._get_parent_by_topic(topic_path)
            super(TopicDict, topic_parent_node).__setitem__(topic_label, value)

        else:
            topic_node._value = value

        if self._listeners:
            for callback in self._listeners:
                # TODO: convert to async?
                callback(topic_path, value)

    def _del(self, topic_path: str):

        topic_parent_node, topic_label = self._get_parent_by_topic(topic_path)

        if not topic_parent_node:
            return False

        return topic_parent_node.pop(topic_label, False)

    def __getitem__(self, topic_path) -> Any:
        return self.get(topic_path)

    def __setitem__(self, topic_path, value):
        self.set(topic_path, value)

    def __delitem__(self, topic_path):
        self._del(topic_path)

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, value):
        self._value = value

        if self._listeners:
            for callback in self._listeners:
                # TODO: convert to async?
                callback("", value)


from .const import TRUE, FALSE


def str2bool(val: str):
    return val == TRUE


def bool2str(val: bool):
    return TRUE if val else FALSE
