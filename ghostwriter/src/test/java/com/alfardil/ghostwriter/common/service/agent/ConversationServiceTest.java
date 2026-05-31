package com.alfardil.ghostwriter.common.service.agent;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.alfardil.ghostwriter.common.db.models.message.Message;
import com.alfardil.ghostwriter.common.db.repos.message.MessageRepository;
import com.alfardil.ghostwriter.common.service.cache.QuestionCacheService;
import com.alfardil.ghostwriter.common.service.llm.LLMClient;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class ConversationServiceTest {

  @Mock
  private LLMClient llmClient;

  @Mock
  private MessageRepository messageRepository;

  @Mock
  private QuestionCacheService cacheService;

  @InjectMocks
  private ConversationService conversationService;

  @Test
  @DisplayName("Cache miss calls the LLM, stores to cache, persists, and returns the fresh reply")
  void cacheMiss() {
    when(cacheService.lookup("user123", "hello")).thenReturn(Optional.empty());
    when(llmClient.generate("hello")).thenReturn("AI response");

    String result = conversationService.respond("user123", "hello");

    assertThat(result).isEqualTo("AI response");
    verify(llmClient).generate("hello");
    verify(cacheService).store("user123", "hello", "AI response");

    ArgumentCaptor<Message> captor = ArgumentCaptor.forClass(Message.class);
    verify(messageRepository).createMessage(captor.capture());
    Message saved = captor.getValue();
    assertThat(saved.getTelegramId()).isEqualTo("user123");
    assertThat(saved.getUserMessage()).isEqualTo("hello");
    assertThat(saved.getAiResponse()).isEqualTo("AI response");
  }

  @Test
  @DisplayName("Cache hit skips the LLM and store, but still persists, and returns the cached reply")
  void cacheHit() {
    when(cacheService.lookup("user123", "hello")).thenReturn(Optional.of("cached reply"));

    String result = conversationService.respond("user123", "hello");

    assertThat(result).isEqualTo("cached reply");
    verify(llmClient, never()).generate(any());
    verify(cacheService, never()).store(any(), any(), any());
    verify(messageRepository).createMessage(any());
  }

  @Test
  @DisplayName("LLM exception is propagated and nothing is persisted")
  void llmThrows() {
    when(cacheService.lookup("user123", "hello")).thenReturn(Optional.empty());
    RuntimeException ex = new RuntimeException("AI error");
    when(llmClient.generate(any())).thenThrow(ex);

    assertThatThrownBy(() -> conversationService.respond("user123", "hello")).isSameAs(ex);
    verify(messageRepository, never()).createMessage(any());
  }

  @Test
  @DisplayName("DB exception is propagated")
  void dbThrows() {
    when(cacheService.lookup("user123", "hello")).thenReturn(Optional.empty());
    when(llmClient.generate(any())).thenReturn("AI response");
    doThrow(new RuntimeException("DB error")).when(messageRepository).createMessage(any());

    assertThatThrownBy(() -> conversationService.respond("user123", "hello"))
      .hasMessage("DB error");
    verify(cacheService).store(eq("user123"), eq("hello"), eq("AI response"));
  }
}
