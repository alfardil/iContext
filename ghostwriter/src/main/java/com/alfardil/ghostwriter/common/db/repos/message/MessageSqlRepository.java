package com.alfardil.ghostwriter.common.db.repos.message;

import com.alfardil.ghostwriter.common.db.models.message.Message;
import java.time.OffsetDateTime;
import java.util.UUID;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;

@Component
public class MessageSqlRepository implements MessageRepository {

  private final JdbcClient client;

  public MessageSqlRepository(final JdbcClient client) {
    this.client = client;
  }

  private final RowMapper<Message> messageMapper = (rs, _) ->
    Message.builder()
      .id(rs.getString("id"))
      .telegramId(rs.getString("telegramId"))
      .userMessage(rs.getString("userMessage"))
      .aiResponse(rs.getString("aiResponse"))
      .createdAt(rs.getObject("createdAt", OffsetDateTime.class))
      .build();

  @Override
  public void createMessage(Message message) {
    UUID id = UUID.randomUUID();
    message.setId(id.toString());

    message.setCreatedAt(
      client
        .sql(
          """
          INSERT INTO "Message" (id, "telegramId", "userMessage", "aiResponse")
          VALUES (:id, :telegramId, :userMessage, :aiResponse)
          RETURNING "createdAt"
          """
        )
        .param("id", id)
        .param("telegramId", message.getTelegramId())
        .param("userMessage", message.getUserMessage())
        .param("aiResponse", message.getAiResponse())
        .query((rs, rowNum) -> rs.getObject("createdAt", OffsetDateTime.class))
        .single()
    );
  }

  @Override
  public Message getMessageById(String id) {
    return client
      .sql(
        """
        SELECT id, "telegramId", "userMessage", "aiResponse", "createdAt"
        FROM "Message"
        WHERE id = :id
        """
      )
      .param("id", UUID.fromString(id))
      .query(messageMapper)
      .optional()
      .orElse(null);
  }

  @Override
  public boolean updateMessage(Message message) {
    int updatedRows = client
      .sql(
        """
        UPDATE "Message"
        SET
          "userMessage" = :userMessage,
          "aiResponse" = :aiResponse
        WHERE id = :id
        """
      )
      .param("userMessage", message.getUserMessage())
      .param("aiResponse", message.getAiResponse())
      .param("id", UUID.fromString(message.getId()))
      .update();

    return updatedRows > 0;
  }

  @Override
  public boolean deleteMessageById(String id) {
    int updatedRows = client
      .sql(
        """
        DELETE FROM "Message"
        WHERE id = :id
        """
      )
      .param("id", UUID.fromString(id))
      .update();

    return updatedRows > 0;
  }
}
