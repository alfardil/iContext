package com.alfardil.ghostwriter.common.db.repos.message;

import static org.assertj.core.api.Assertions.assertThat;

import com.alfardil.ghostwriter.common.db.models.message.Message;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.kafka.test.context.EmbeddedKafka;
import org.springframework.test.context.ActiveProfiles;

@SpringBootTest
@ActiveProfiles("test")
@EmbeddedKafka(partitions = 1, topics = {"task", "reply"})
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class MessageSqlRepositoryIntegrationTest {

  @Autowired
  private MessageSqlRepository repository;

  private final List<String> createdIds = new ArrayList<>();

  @AfterAll
  void cleanup() {
    createdIds.forEach(repository::deleteMessageById);
  }

  private Message insert(
    String telegramId,
    String userMessage,
    String aiResponse
  ) {
    Message message = Message.builder()
      .telegramId(telegramId)
      .userMessage(userMessage)
      .aiResponse(aiResponse)
      .build();
    repository.createMessage(message);
    createdIds.add(message.getId());
    return message;
  }

  @Test
  @DisplayName("createMessage assigns a UUID id and a createdAt timestamp")
  void createMessage() {
    Message message = insert("tg-1", "hello", "world");

    assertThat(message.getId()).isNotNull();
    assertThat(message.getCreatedAt()).isNotNull();
  }

  @Test
  @DisplayName("getMessageById returns the inserted message with all fields")
  void getMessageById() {
    Message inserted = insert("tg-2", "user msg", "ai reply");

    Message fetched = repository.getMessageById(inserted.getId());

    assertThat(fetched).isNotNull();
    assertThat(fetched.getId()).isEqualTo(inserted.getId());
    assertThat(fetched.getTelegramId()).isEqualTo("tg-2");
    assertThat(fetched.getUserMessage()).isEqualTo("user msg");
    assertThat(fetched.getAiResponse()).isEqualTo("ai reply");
    assertThat(fetched.getCreatedAt()).isNotNull();
  }

  @Test
  @DisplayName("getMessageById returns null for an unknown id")
  void getMessageByIdNotFound() {
    assertThat(
      repository.getMessageById("00000000-0000-0000-0000-000000000000")
    ).isNull();
  }

  @Test
  @DisplayName(
    "updateMessage modifies userMessage and aiResponse and returns true"
  )
  void updateMessage() {
    Message message = insert("tg-3", "original", "original reply");

    message.setUserMessage("updated");
    message.setAiResponse("updated reply");
    boolean result = repository.updateMessage(message);

    assertThat(result).isTrue();
    Message fetched = repository.getMessageById(message.getId());
    assertThat(fetched.getUserMessage()).isEqualTo("updated");
    assertThat(fetched.getAiResponse()).isEqualTo("updated reply");
  }

  @Test
  @DisplayName("updateMessage returns false for an unknown id")
  void updateMessageNotFound() {
    Message ghost = Message.builder()
      .id("00000000-0000-0000-0000-000000000000")
      .telegramId("x")
      .userMessage("x")
      .aiResponse("x")
      .build();

    assertThat(repository.updateMessage(ghost)).isFalse();
  }

  @Test
  @DisplayName("deleteMessageById removes the row and returns true")
  void deleteMessageById() {
    Message message = insert("tg-4", "to delete", "bye");
    String id = message.getId();

    boolean deleted = repository.deleteMessageById(id);

    assertThat(deleted).isTrue();
    assertThat(repository.getMessageById(id)).isNull();
    createdIds.remove(id);
  }

  @Test
  @DisplayName("deleteMessageById returns false for an unknown id")
  void deleteMessageByIdNotFound() {
    assertThat(
      repository.deleteMessageById("00000000-0000-0000-0000-000000000000")
    ).isFalse();
  }
}
