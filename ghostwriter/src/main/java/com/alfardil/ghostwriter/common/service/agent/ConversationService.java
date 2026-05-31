package com.alfardil.ghostwriter.common.service.agent;

import com.alfardil.ghostwriter.common.db.models.message.Message;
import com.alfardil.ghostwriter.common.db.repos.message.MessageRepository;
import com.alfardil.ghostwriter.common.service.cache.QuestionCacheService;
import com.alfardil.ghostwriter.common.service.llm.LLMClient;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

/**
 * The profile-agnostic core of a turn: semantic-cache lookup, else LLM, persist, return the reply.
 *
 * <p>Both ingress paths call this. In dev the Kafka {@code AgentService} calls it from the task
 * listener; in prod the inline intake calls it on a background thread. Keeping it here means the
 * cache/LLM/persist logic lives in exactly one place regardless of how the message arrived.
 */
@Slf4j
@Service
public class ConversationService {

  private final LLMClient llmClient;
  private final MessageRepository messageRepository;
  private final QuestionCacheService cacheService;

  public ConversationService(
    final LLMClient llmClient,
    final MessageRepository messageRepository,
    final QuestionCacheService cacheService
  ) {
    this.llmClient = llmClient;
    this.messageRepository = messageRepository;
    this.cacheService = cacheService;
  }

  /** Produce the AI reply for one user message and persist the exchange. */
  public String respond(String userId, String userMessage) {
    String aiResponse = cacheService
      .lookup(userId, userMessage)
      .orElseGet(() -> {
        String fresh = llmClient.generate(userMessage);
        cacheService.store(userId, userMessage, fresh);
        return fresh;
      });

    Message message = Message.builder()
      .telegramId(userId)
      .userMessage(userMessage)
      .aiResponse(aiResponse)
      .build();
    messageRepository.createMessage(message);

    return aiResponse;
  }
}
