"""Omnesis as a conversation agent for Assist."""

from __future__ import annotations

from typing import Literal

from homeassistant.components import conversation
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import intent
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .answer import async_ask
from .api import Answer
from .coordinator import OmnesisConfigEntry
from .entity import OmnesisEntity

# One question at a time per entity; the gateway queues the rest anyway.
PARALLEL_UPDATES = 0

# Assist conversations whose Omnesis conversation is remembered.
MAX_CONVERSATIONS = 100

# Spoken replies for verdicts without an answer, by language prefix.
_MESSAGES = {
    "en": {
        "approval_required": (
            "Omnesis would only release this answer after you approve it, and "
            "Home Assistant cannot approve answers. Choose an access level for "
            "Home Assistant in the Omnesis portal that does not hold answers for approval."
        ),
        "denied": "Omnesis withheld the answer ({reason}).",
        "reductions": "Some details were withheld: {reductions}.",
    },
    "it": {
        "approval_required": (
            "Omnesis rilascerebbe questa risposta solo dopo la tua approvazione, "
            "che Home Assistant non può dare. Nel portale di Omnesis scegli per "
            "Home Assistant un livello di accesso che non richieda approvazione."
        ),
        "denied": "Omnesis non ha rilasciato la risposta ({reason}).",
        "reductions": "Alcuni dettagli sono stati omessi: {reductions}.",
    },
}


def _messages(language: str) -> dict[str, str]:
    return _MESSAGES.get(language.split("-")[0].lower(), _MESSAGES["en"])


def speech_for(answer: Answer, language: str) -> str:
    """Return what to say for a gateway verdict."""
    messages = _messages(language)
    if answer.status == "released":
        return answer.answer or ""
    if answer.status == "released_with_reductions":
        text = answer.answer or ""
        if answer.reductions:
            text += "\n\n" + messages["reductions"].format(reductions="; ".join(answer.reductions))
        return text
    if answer.status == "approval_required":
        return messages["approval_required"]
    return messages["denied"].format(reason=answer.reason or answer.status)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OmnesisConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the conversation agent."""
    async_add_entities([OmnesisConversationEntity(entry)])


class OmnesisConversationEntity(OmnesisEntity, conversation.ConversationEntity):
    """Answers Assist with Omnesis."""

    _attr_name = None
    _attr_supported_features = conversation.ConversationEntityFeature(0)

    def __init__(self, entry: OmnesisConfigEntry) -> None:
        """Initialize the agent."""
        super().__init__(entry.runtime_data.coordinator, "conversation")
        self.entry = entry

    @property
    def available(self) -> bool:
        """Stay available: a failed question explains itself."""
        return True

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Omnesis answers in whatever language it is asked."""
        return MATCH_ALL

    async def _async_handle_message(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        """Ask Omnesis and add its reply to the chat log."""
        conversations = self.entry.runtime_data.conversations
        try:
            answer = await async_ask(
                self.hass,
                self.entry,
                user_input.text,
                conversations.get(chat_log.conversation_id),
            )
        except HomeAssistantError as err:
            intent_response = intent.IntentResponse(language=user_input.language)
            intent_response.async_set_error(
                intent.IntentResponseErrorCode.UNKNOWN,
                # Already a readable, translated reason.
                str(err) or type(err).__name__,
            )
            return conversation.ConversationResult(
                response=intent_response, conversation_id=chat_log.conversation_id
            )

        if answer.conversation_id:
            # Follow-ups in this Assist conversation continue the same Omnesis one.
            conversations.pop(chat_log.conversation_id, None)
            conversations[chat_log.conversation_id] = answer.conversation_id
            while len(conversations) > MAX_CONVERSATIONS:
                del conversations[next(iter(conversations))]
        chat_log.async_add_assistant_content_without_tools(
            conversation.AssistantContent(
                agent_id=user_input.agent_id,
                content=speech_for(answer, user_input.language),
            )
        )
        return conversation.async_get_result_from_chat_log(user_input, chat_log)
