from typing import TypedDict, Optional, List

class ConversationState(TypedDict):
    user_id:           str
    session_id:        str
    messages:          List[dict]          # Full turn history [{role, content, timestamp}]
    current_message:   str                 # Current user input
    detected_emotion:  Optional[str]       # Emotion label from voice/text classifier
    emotion_pad:       Optional[dict]      # {valence, arousal, dominance}
    safety_flag:       Optional[str]       # None | "escalate" | "crisis" | "safe"
    kg_context:        Optional[str]       # Formatted context block from retrieval
    response_draft:    Optional[str]       # LLM output before post-guardrail
    final_response:    Optional[str]       # Post-guardrail approved response
    cbt_node_active:   Optional[str]       # Active CBT intervention node name
    phq9_state:        Optional[dict]      # Mid-assessment tracker
    session_turn:      int                 # Turn counter within session