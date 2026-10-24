
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage


def parse_messages(messages):
  parsed_messages=[]
  for msg in messages:
      if msg.get("role")=="user":
        parsed_messages.append(HumanMessage(content=msg.get("content")))
      elif msg.get("role")=="assistant":
        parsed_messages.append(AIMessage(content=msg.get("content")))
      elif msg.get("role")=="system":
        parsed_messages.append(SystemMessage(content=msg.get("content")))
  return parsed_messages