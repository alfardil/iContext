package com.alfardil.ghostwriter.common.service.llm;

import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.stereotype.Component;

@Component
public class LLMClient {

  private final ChatClient chatClient;
  private final ToolCallback[] toolCallbacks;

  public LLMClient(ChatClient.Builder builder, AgentToolset toolset) {
    this.chatClient = builder.defaultSystem(toolset.systemPrompt()).build();
    this.toolCallbacks = toolset.callbacks();
  }

  public String generate(String userMessage) {
    return chatClient
      .prompt()
      .user(userMessage)
      .toolCallbacks(toolCallbacks)
      .call()
      .content();
  }
}
