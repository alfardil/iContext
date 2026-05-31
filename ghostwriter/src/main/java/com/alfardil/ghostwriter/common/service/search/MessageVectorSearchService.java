package com.alfardil.ghostwriter.common.service.search;

import com.alfardil.ghostwriter.common.db.repos.vector.MessageVectorRepository;
import com.alfardil.ghostwriter.common.db.repos.vector.MessageVectorRepository.MessageHit;
import java.time.Duration;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.embedding.EmbeddingModel;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Service;

/**
 * The {@code prod}-profile replacement for the Mac's {@code semantic_search_messages} MCP tool.
 * It embeds the query with the same in-process MiniLM-L6 model used for the question cache, then
 * runs a pgvector KNN against the {@code MessageVector} replica the Mac publishes into. No call to
 * the Mac happens at request time, so the bot answers from the last sync even while the Mac sleeps.
 */
@Slf4j
@Service
public class MessageVectorSearchService {

  /** If the freshest synced message is older than this, warn the user the Mac may be asleep. */
  private static final Duration STALE_AFTER = Duration.ofHours(1);

  private final EmbeddingModel embeddingModel;
  private final MessageVectorRepository repo;

  public MessageVectorSearchService(
    final EmbeddingModel embeddingModel,
    final MessageVectorRepository repo
  ) {
    this.embeddingModel = embeddingModel;
    this.repo = repo;
  }

  /** What the model sees back: the hits plus an honest freshness note. */
  public record SearchResponse(List<MessageHit> hits, String freshnessNote) {}

  @Tool(
    name = "search_messages",
    description = """
      Search the user's iMessage history by meaning (semantic / vector search). Use this for any
      question about what was said in past messages. Works for both exact phrases ('spa', 'Friday
      at 8') and conceptual queries ('feeling overwhelmed', 'plans about traveling').
      Optionally narrow by the other person's name, and/or a date range."""
  )
  public SearchResponse searchMessages(
    @ToolParam(description = "Natural-language description of what to find.")
    String query,
    @ToolParam(required = false, description = "Filter to a person by contact-name substring (case-insensitive), e.g. 'Sheza'.")
    String senderName,
    @ToolParam(required = false, description = "Only messages on/after this date. ISO 'YYYY-MM-DD' (UTC).")
    String since,
    @ToolParam(required = false, description = "Only messages before this date. ISO 'YYYY-MM-DD' (UTC).")
    String until,
    @ToolParam(required = false, description = "Max number of hits to return (default 20).")
    Integer topK
  ) {
    int k = topK == null || topK <= 0 ? 20 : Math.min(topK, 100);
    float[] embedding = embeddingModel.embed(query);
    List<MessageHit> hits = repo.search(embedding, senderName, parseDate(since), parseDate(until), k);
    log.info("search_messages: '{}' senderName={} → {} hits", query, senderName, hits.size());
    return new SearchResponse(hits, freshnessNote());
  }

  private String freshnessNote() {
    return repo
      .latestSyncedAt()
      .filter(ts -> Duration.between(ts, OffsetDateTime.now()).compareTo(STALE_AFTER) > 0)
      .map(ts -> {
        long minutes = Duration.between(ts, OffsetDateTime.now()).toMinutes();
        return "Messages were last synced ~" + humanizeMinutes(minutes)
          + " ago (my Mac may be asleep), so very recent messages might be missing.";
      })
      .orElse(null);
  }

  private static OffsetDateTime parseDate(String s) {
    if (s == null || s.isBlank()) return null;
    try {
      return LocalDate.parse(s.trim()).atStartOfDay().atOffset(ZoneOffset.UTC);
    } catch (Exception ignored) {
      try {
        return OffsetDateTime.parse(s.trim());
      } catch (Exception alsoIgnored) {
        return null;
      }
    }
  }

  private static String humanizeMinutes(long minutes) {
    if (minutes < 90) return minutes + " minutes";
    long hours = minutes / 60;
    if (hours < 36) return hours + " hours";
    return (hours / 24) + " days";
  }
}
