import os
from dotenv import load_dotenv
from uagents_core.utils.registration import (
    register_chat_agent,
    RegistrationRequestCredentials,
)

load_dotenv()

register_chat_agent(
    "MedPage Operator",
    "https://enamel-reclusive-factor.ngrok-free.dev",
    active=True,
    credentials=RegistrationRequestCredentials(
        agentverse_api_key=os.environ["AGENTVERSE_KEY"],
        agent_seed_phrase=os.getenv("OPERATOR_SEED", "operator-dev-seed"),        
    ),
)