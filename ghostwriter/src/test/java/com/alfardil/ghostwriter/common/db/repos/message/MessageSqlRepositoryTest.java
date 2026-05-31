package com.alfardil.ghostwriter.common.db.repos.message;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.alfardil.ghostwriter.common.db.models.message.Message;
import java.lang.reflect.Field;
import java.util.UUID;
import java.sql.ResultSet;
import java.time.OffsetDateTime;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.simple.JdbcClient;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class MessageSqlRepositoryTest {

  @Mock
  private JdbcClient jdbcClient;

  @InjectMocks
  private MessageSqlRepository repository;

  @Mock
  private JdbcClient.StatementSpec statementSpec;

  @BeforeEach
  void setUp() {
    when(jdbcClient.sql(anyString())).thenReturn(statementSpec);
    when(statementSpec.param(anyString(), any())).thenReturn(statementSpec);
  }

  @Test
  @DisplayName("createMessage sets id and createdAt from DB")
  @SuppressWarnings("unchecked")
  void createMessage() {
    JdbcClient.MappedQuerySpec<OffsetDateTime> querySpec = mock(
      JdbcClient.MappedQuerySpec.class
    );
    OffsetDateTime now = OffsetDateTime.now();
    when(statementSpec.query(any(RowMapper.class))).thenReturn(querySpec);
    when(querySpec.single()).thenReturn(now);

    Message message = Message.builder()
      .telegramId("123")
      .userMessage("hello")
      .aiResponse("world")
      .build();

    repository.createMessage(message);

    assertThat(message.getId()).isNotNull();
    assertThat(message.getCreatedAt()).isEqualTo(now);
    verify(jdbcClient).sql(contains("INSERT"));
    verify(statementSpec).param("telegramId", "123");
    verify(statementSpec).param("userMessage", "hello");
    verify(statementSpec).param("aiResponse", "world");
  }

  @Test
  @DisplayName("getMessageById returns message when found")
  @SuppressWarnings("unchecked")
  void getByIdFound() {
    JdbcClient.MappedQuerySpec<Message> querySpec = mock(
      JdbcClient.MappedQuerySpec.class
    );
    Message expected = Message.builder()
      .id("00000000-0000-0000-0000-000000000001")
      .telegramId("123")
      .userMessage("hello")
      .aiResponse("world")
      .createdAt(OffsetDateTime.now())
      .build();
    when(statementSpec.query(any(RowMapper.class))).thenReturn(querySpec);
    when(querySpec.optional()).thenReturn(Optional.of(expected));

    assertThat(repository.getMessageById("00000000-0000-0000-0000-000000000001")).isEqualTo(expected);
    verify(jdbcClient).sql(contains("SELECT"));
  }

  @Test
  @DisplayName("getMessageById returns null when not found")
  @SuppressWarnings("unchecked")
  void getByIdNotFound() {
    JdbcClient.MappedQuerySpec<Message> querySpec = mock(
      JdbcClient.MappedQuerySpec.class
    );
    when(statementSpec.query(any(RowMapper.class))).thenReturn(querySpec);
    when(querySpec.optional()).thenReturn(Optional.empty());

    assertThat(repository.getMessageById("00000000-0000-0000-0000-000000000000")).isNull();
  }

  @Test
  @DisplayName("updateMessage returns true when row is updated")
  void updateFound() {
    when(statementSpec.update()).thenReturn(1);

    Message message = Message.builder()
      .id("00000000-0000-0000-0000-000000000001")
      .telegramId("123")
      .userMessage("updated text")
      .aiResponse("new response")
      .build();

    assertThat(repository.updateMessage(message)).isTrue();
    verify(jdbcClient).sql(contains("UPDATE"));
    verify(statementSpec).param("userMessage", "updated text");
    verify(statementSpec).param("aiResponse", "new response");
    verify(statementSpec).param("id", UUID.fromString("00000000-0000-0000-0000-000000000001"));
  }

  @Test
  @DisplayName("updateMessage returns false when row not found")
  void updateNotFound() {
    when(statementSpec.update()).thenReturn(0);

    Message message = Message.builder()
      .id("00000000-0000-0000-0000-000000000000")
      .telegramId("t")
      .userMessage("u")
      .aiResponse("a")
      .build();

    assertThat(repository.updateMessage(message)).isFalse();
  }

  @Test
  @DisplayName("deleteMessageById returns true when row is deleted")
  void deleteFound() {
    when(statementSpec.update()).thenReturn(1);

    assertThat(repository.deleteMessageById("00000000-0000-0000-0000-000000000001")).isTrue();
    verify(jdbcClient).sql(contains("DELETE"));
    verify(statementSpec).param("id", UUID.fromString("00000000-0000-0000-0000-000000000001"));
  }

  @Test
  @DisplayName("deleteMessageById returns false when row not found")
  void deleteNotFound() {
    when(statementSpec.update()).thenReturn(0);

    assertThat(repository.deleteMessageById("00000000-0000-0000-0000-000000000000")).isFalse();
  }

  @Test
  @DisplayName("RowMapper correctly maps all ResultSet columns to Message")
  @SuppressWarnings("unchecked")
  void rowMapper() throws Exception {
    Field mapperField = MessageSqlRepository.class.getDeclaredField(
      "messageMapper"
    );
    mapperField.setAccessible(true);
    RowMapper<Message> mapper = (RowMapper<Message>) mapperField.get(repository);

    ResultSet rs = mock(ResultSet.class);
    OffsetDateTime createdAt = OffsetDateTime.now();
    when(rs.getString("id")).thenReturn("uuid-1");
    when(rs.getString("telegramId")).thenReturn("user123");
    when(rs.getString("userMessage")).thenReturn("hello");
    when(rs.getString("aiResponse")).thenReturn("world");
    when(rs.getObject("createdAt", OffsetDateTime.class)).thenReturn(createdAt);

    Message result = mapper.mapRow(rs, 1);

    assertThat(result.getId()).isEqualTo("uuid-1");
    assertThat(result.getTelegramId()).isEqualTo("user123");
    assertThat(result.getUserMessage()).isEqualTo("hello");
    assertThat(result.getAiResponse()).isEqualTo("world");
    assertThat(result.getCreatedAt()).isEqualTo(createdAt);
  }
}
