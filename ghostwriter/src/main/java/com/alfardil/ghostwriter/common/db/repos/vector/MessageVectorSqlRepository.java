package com.alfardil.ghostwriter.common.db.repos.vector;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;

@Component
public class MessageVectorSqlRepository implements MessageVectorRepository {

  private final JdbcClient client;

  public MessageVectorSqlRepository(final JdbcClient client) {
    this.client = client;
  }

  @Override
  public List<MessageHit> search(
    float[] embedding,
    String senderName,
    OffsetDateTime since,
    OffsetDateTime until,
    int limit
  ) {
    String vec = toVectorLiteral(embedding);
    String senderPat = senderName == null || senderName.isBlank() ? null : "%" + senderName.trim() + "%";
    return client
      .sql(
        """
        SELECT "msgGuid", "chatGuid", "sentAt", "sender", "senderName", "isFromMe", "text",
               1 - ("embedding" <=> CAST(:vec AS vector)) AS score
        FROM "MessageVector"
        WHERE (CAST(:senderPat AS text) IS NULL OR "senderName" ILIKE CAST(:senderPat AS text))
          AND (CAST(:since AS timestamptz) IS NULL OR "sentAt" >= CAST(:since AS timestamptz))
          AND (CAST(:until AS timestamptz) IS NULL OR "sentAt" <  CAST(:until AS timestamptz))
        ORDER BY "embedding" <=> CAST(:vec AS vector)
        LIMIT :limit
        """
      )
      .param("vec", vec)
      .param("senderPat", senderPat)
      .param("since", since)
      .param("until", until)
      .param("limit", limit)
      .query((rs, rowNum) ->
        new MessageHit(
          rs.getString("sentAt"),
          rs.getString("sender"),
          rs.getString("senderName"),
          rs.getBoolean("isFromMe"),
          rs.getString("chatGuid"),
          rs.getString("text"),
          rs.getDouble("score")
        )
      )
      .list();
  }

  @Override
  public Optional<OffsetDateTime> latestSyncedAt() {
    return client
      .sql("SELECT MAX(\"sentAt\") FROM \"MessageVector\"")
      .query(OffsetDateTime.class)
      .optional();
  }

  private static String toVectorLiteral(float[] arr) {
    StringBuilder sb = new StringBuilder(arr.length * 8 + 2);
    sb.append('[');
    for (int i = 0; i < arr.length; i++) {
      if (i > 0) sb.append(',');
      sb.append(arr[i]);
    }
    sb.append(']');
    return sb.toString();
  }
}
