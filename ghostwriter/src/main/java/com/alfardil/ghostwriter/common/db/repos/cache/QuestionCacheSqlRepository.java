package com.alfardil.ghostwriter.common.db.repos.cache;

import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;

@Component
public class QuestionCacheSqlRepository implements QuestionCacheRepository {

  private final JdbcClient client;

  public QuestionCacheSqlRepository(final JdbcClient client) {
    this.client = client;
  }

  @Override
  public Optional<String> findSimilar(String userId, float[] embedding, double maxDistance) {
    return client
      .sql(
        """
        SELECT "aiResponse"
        FROM "QuestionCache"
        WHERE "userId" = :userId
          AND "expiresAt" > NOW()
          AND ("embedding" <=> CAST(:embedding AS vector)) < :maxDistance
        ORDER BY "embedding" <=> CAST(:embedding AS vector)
        LIMIT 1
        """
      )
      .param("userId", userId)
      .param("embedding", toVectorLiteral(embedding))
      .param("maxDistance", maxDistance)
      .query(String.class)
      .optional();
  }

  @Override
  public void save(
    String userId,
    String question,
    float[] embedding,
    String aiResponse,
    Duration ttl
  ) {
    client
      .sql(
        """
        INSERT INTO "QuestionCache"
          (id, "userId", "question", "embedding", "aiResponse", "expiresAt")
        VALUES
          (:id, :userId, :question, CAST(:embedding AS vector), :aiResponse, :expiresAt)
        """
      )
      .param("id", UUID.randomUUID())
      .param("userId", userId)
      .param("question", question)
      .param("embedding", toVectorLiteral(embedding))
      .param("aiResponse", aiResponse)
      .param("expiresAt", OffsetDateTime.now().plus(ttl))
      .update();
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
