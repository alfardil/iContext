package com.alfardil.ghostwriter.common.db.repos.cache;

import java.time.Duration;
import java.util.Optional;

public interface QuestionCacheRepository {

  // Returns the cached aiResponse for the closest non-expired entry within `maxDistance`
  // (cosine distance, lower is more similar). Empty if no hit.
  Optional<String> findSimilar(String userId, float[] embedding, double maxDistance);

  void save(String userId, String question, float[] embedding, String aiResponse, Duration ttl);
}
