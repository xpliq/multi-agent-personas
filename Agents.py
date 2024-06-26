import random
import asyncio
import os
import openai
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv('OPENAI_API_KEY')
openai.api_key = api_key

semaphore = asyncio.Semaphore(128)

class Agent:
    def __init__(self, client, name, sysprompt, task):
        self.client = client
        self.name = name
        self.sysprompt = sysprompt
        self.task = task
        self.memory = []
        self.path = []
        self.current_partner = None
        self.conversation_history = []

    # method to grab conversation history from an agent
    def get_conversation_history(self):
        conversation_str = "Conversation History for " + self.name + ":\n"
        for resp in self.conversation_history:
            conversation_str += resp + "\n"
        return conversation_str

    # Structures a prompt from a template. Useful for models that benefit from more structural prompts
    async def genprompt(self):
        current_partner_sysprompt = getattr(self.current_partner, 'sysprompt', 'None')
        
        prompt = (f"{self.sysprompt} After reading through your role, memory, and conversation history, "
                  f"you will respond to instructions given to you by 'Instruction:'. Task: {self.task} "
                  f"You may or may not have already spoken with other Agents. However, your current "
                  f"Agent that you will collaborate with is: {self.current_partner}. This is your current "
                  f"partner's role: {current_partner_sysprompt}. ")
        
        # ensuring the agent is aware of having a partner. Otherwise just introduce itself so that it understands themselves better
        if self.current_partner is None:
            prompt += ("If you currently have no partner, introduce yourself and layout the foundation to how you would tackle the given task with your specialization and expertise. ")
        else:
            prompt += "Collaborate on the given task with your partner. "
        
        # adding more to the prompt for better understanding of who the agent is
        prompt += (f"This is your inner memory and past thoughts: {self.memory} "
                   f"Your conversation history: {self.conversation_history}")
        return prompt

    # this generates responses from agent's model given a prompt
    async def instruct(self, instruction):
        async with semaphore:
            prompt = await self.genprompt() + f"\nInstruction: {instruction}"
            
            messages = [
                {"role": "system", "content": prompt}
            ]
            
            response = await self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0.9, 
                max_tokens=150
            )
            
            return response.choices[0].message.content.strip().replace('\n', '')

    # this particular method is to prompt an agent to reply to a given conversation
    async def reply(self, conversation, current_partner):
        instruction = "Please add your reply to the conversation. Only provide your response. Stay on Task. Respond using your specialization, memory, and expertise. Keep your responses relevant to your role and the ongoing discussion. Be detailed."
        return await self.instruct(instruction)

    # agent's are to update their memory after each conversation/dialogue
    async def update_memory(self):
        instruction = "Reflect on the current conversation and task, and add to your internal thoughts anything new you've learned or plan to remember for future reference."
        new_memory = await self.instruct(instruction)
        self.memory.append(new_memory)

    # looped for agents to collaborate through their entire generated path of agents
    async def collaborate_with(self, partner_agent):
        self.current_partner = partner_agent
        conversation_str = "\n".join(self.conversation_history)
        your_response = await self.instruct("Add your contribution to the task at hand.")
        their_response = await partner_agent.reply(conversation_str, self)
        self.conversation_history.extend([f"{self.name}: {your_response}", f"{partner_agent.name}: {their_response}"])
        await self.update_memory()
        
        print(f"\n{self.name} & {partner_agent.name} Collaboration:")
        print(f"{self.name}: {your_response}")
        print(f"{partner_agent.name}: {their_response}")
        
        self.current_partner = None
        
    # generates the required parameters needed for multiple agents -- relative to a given user prompt
    async def process_prompt_to_roles(self, user_prompt):
        # Expand the prompt
        expanded_prompt_instruction = f"You will be given a prompt. Expand on the prompt and create a new prompt. This expanded task should delve deeper into the user's initial request, providing clarity, focus, and direction. Ensure your expansion maintains consistency with the original prompt and enhances its conciseness and specificity. You response should only be the new prompt, nothing else. \n User Prompt: {user_prompt}"
        
        async with semaphore:
            messages = [
                {"role": "system", "content": expanded_prompt_instruction}
            ]
            
            response = await self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0.9,
                max_tokens=150 
            )
        
        response_output = response.choices[0].message.content.strip().replace('\n', '')
        
        # Create parameters from the expanded prompt
        params_instruction = (
            f"Given the following prompt, list out the key topics that should be addressed. Only provide the topics in your response."
            f"List the topics as a comma-separated list and do not number them.\nPrompt: {response_output}"
        )
        
        async with semaphore:
            messages = [
                {"role": "system", "content": params_instruction}
            ]
            
            response = await self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0.9,
                max_tokens=150 
            )
        
        topics_text = response.choices[0].message.content.strip().replace('\n', '')
        topics_list = [topic.strip() for topic in topics_text.split(',')]
        
        # Generate roles based on the topics
        roles = [f"You are Agent {i + 1}. You are an expert in {topic}." for i, topic in enumerate(topics_list)]

        return response_output, topics_list, roles

    # generates a path of collaboration for agent
    def generate_path(self, agent_names):
        # this path is generated as a method to have multiple agent conversations happen at once to improve speed of conversation generation
        self.path = [name for name in agent_names if name != self.name]
        random.shuffle(self.path)

class Group:
    def __init__(self, task, agents):
        self.task = task
        self.agents = agents

    # executes the generated path in that order
    async def execute_path(self, agent):
        await agent.update_memory()
        for partner_name in agent.path:
            partner_agent = next(a for a in self.agents if a.name == partner_name)
            await agent.collaborate_with(partner_agent)

    # starts collaboration between all the agents
    async def conduct_collaborations(self):
        tasks = [self.execute_path(agent) for agent in self.agents]
        await asyncio.gather(*tasks)
