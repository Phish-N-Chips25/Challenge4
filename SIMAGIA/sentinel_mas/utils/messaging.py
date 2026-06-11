"""FIPA-ACL message construction helpers for SPADE."""

import json
from spade.message import Message

# ── Ontology constants ───────────────────────────────────────
ONTOLOGY = "sentinel-mas"
LANGUAGE = "JSON"

# ── Performatives ────────────────────────────────────────────
INFORM           = "inform"
REQUEST          = "request"
PROPOSE          = "propose"
CFP              = "cfp"
AGREE            = "agree"
REFUSE           = "refuse"
FAILURE          = "failure"
ACCEPT_PROPOSAL  = "accept-proposal"   # Contract Net: award to winning bidder
REJECT_PROPOSAL  = "reject-proposal"   # Contract Net: reject the losing bidders


def build_msg(
    to: str,
    performative: str,
    body: dict,
    *,
    thread: str | None = None,
    metadata: dict | None = None,
) -> Message:
    """Build a FIPA-ACL compliant SPADE message.

    Parameters
    ----------
    to : str
        Recipient JID.
    performative : str
        FIPA performative (inform, request, propose …).
    body : dict
        JSON-serialisable payload.
    thread : str, optional
        Conversation thread identifier.
    metadata : dict, optional
        Extra metadata key-value pairs.
    """
    msg = Message(to=to)
    msg.set_metadata("performative", performative)
    msg.set_metadata("ontology", ONTOLOGY)
    msg.set_metadata("language", LANGUAGE)
    if thread:
        msg.thread = thread
    if metadata:
        for k, v in metadata.items():
            msg.set_metadata(k, str(v))
    msg.body = json.dumps(body)
    return msg


def parse_body(msg: Message) -> dict:
    """Parse the JSON body of a received SPADE message."""
    try:
        return json.loads(msg.body)
    except (json.JSONDecodeError, TypeError):
        return {}
