package com.alfardil.ghostwriter.common.service.cache;

import com.alfardil.ghostwriter.common.db.repos.cache.QuestionCacheRepository;
import java.time.Duration;
import java.util.Optional;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.embedding.EmbeddingModel;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

@Slf4j
@Service
public class QuestionCacheService {

  private final EmbeddingModel embeddingModel;
  private final QuestionCacheRepository repo;
  private final double similarityThreshold;
  private final Duration ttl;

  public QuestionCacheService(
    final EmbeddingModel embeddingModel,
    final QuestionCacheRepository repo,
    @Value("${app.cache.similarity-threshold:0.90}") final double similarityThreshold,
    @Value("${app.cache.ttl:1h}") final Duration ttl
  ) {
    this.embeddingModel = embeddingModel;
    this.repo = repo;
    this.similarityThreshold = similarityThreshold;
    this.ttl = ttl;
  }

  public Optional<String> lookup(String userId, String userMessage) {
    float[] embedding = embeddingModel.embed(userMessage);
    double maxDistance = 1.0 - similarityThreshold; // pgvector <=> is cosine distance
    Optional<String> hit = repo.findSimilar(userId, embedding, maxDistance);
    if (hit.isPresent()) {
      log.info("cache hit (userId={}, threshold={})", userId, similarityThreshold);
    } else {
      log.info("cache miss (userId={})", userId);
    }
    return hit;
  }

  public void store(String userId, String userMessage, String aiResponse) {
    float[] embedding = embeddingModel.embed(userMessage);
    repo.save(userId, userMessage, embedding, aiResponse, ttl);
  }
}
