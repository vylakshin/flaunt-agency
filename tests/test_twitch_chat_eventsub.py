import unittest
from unittest.mock import patch

from app.runtime_state import InMemoryRuntimeStateStore
from app.twitch_chat_eventsub import TwitchChatListener


class TwitchChatListenerTests(unittest.TestCase):
    def test_duplicate_chat_event_is_ignored_by_message_id(self) -> None:
        with patch('app.twitch_chat_eventsub.runtime_state', new=InMemoryRuntimeStateStore(namespace='test-chat')):
            listener = TwitchChatListener()
            event = {'message_id': 'msg-1', 'broadcaster_user_id': '123'}

            first_seen = listener._remember_chat_event(event, '')
            second_seen = listener._remember_chat_event(event, '')

            self.assertFalse(first_seen)
            self.assertTrue(second_seen)

    def test_delivery_id_is_used_when_message_id_is_missing(self) -> None:
        with patch('app.twitch_chat_eventsub.runtime_state', new=InMemoryRuntimeStateStore(namespace='test-chat')):
            listener = TwitchChatListener()
            event = {'broadcaster_user_id': '123'}

            first_seen = listener._remember_chat_event(event, 'delivery-1')
            second_seen = listener._remember_chat_event(event, 'delivery-1')

            self.assertFalse(first_seen)
            self.assertTrue(second_seen)

    def test_dedupe_is_shared_across_listener_instances(self) -> None:
        store = InMemoryRuntimeStateStore(namespace='test-chat')
        event = {'message_id': 'msg-2', 'broadcaster_user_id': '555'}

        with patch('app.twitch_chat_eventsub.runtime_state', new=store):
            first_listener = TwitchChatListener()
            second_listener = TwitchChatListener()

            self.assertFalse(first_listener._remember_chat_event(event, ''))
            self.assertTrue(second_listener._remember_chat_event(event, ''))
