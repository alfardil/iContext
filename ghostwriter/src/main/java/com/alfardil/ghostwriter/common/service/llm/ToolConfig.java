package com.alfardil.ghostwriter.common.service.llm;

import com.alfardil.ghostwriter.common.service.search.MessageVectorSearchService;
import org.springframework.ai.mcp.SyncMcpToolCallbackProvider;
import org.springframework.ai.support.ToolCallbacks;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

/**
 * Picks the agent's tools + prompt by profile. Default (dev): the Mac's MCP tools, discovered over
 * HTTP. {@code prod}: the in-process pgvector search tool, so the Mac is never in the request path
 * and the bot answers from the last sync even while the Mac sleeps (see DEPLOYMENT.md).
 */
@Configuration
public class ToolConfig {

  /** Telegram-HTML output rules, shared by both prompts. */
  private static final String OUTPUT_FORMAT = """
    OUTPUT FORMAT — IMPORTANT:
    Your reply is rendered in Telegram with parse_mode=HTML. Use these tags and only these:
      <b>bold</b>, <i>italic</i>, <u>underline</u>, <s>strikethrough</s>,
      <code>inline code</code>, <pre>multiline code</pre>, <a href="...">link</a>.
    Do NOT use Markdown asterisks (no **bold**, no *italic*). Plain text for numbered or
    bulleted lists: write "1. Foo" on its own line. Use real newlines (\\n).
    If quoted message text contains the characters &, <, or >, escape them as &amp;, &lt;, &gt;.

    Summarize results in plain prose with dates; quote at most the most relevant lines.
    If the user's question has nothing to do with messages, answer directly without tools.
    Be clear and concise.""";

  private static final String DEV_PROMPT = """
    You are "Ghostwriter", a Telegram assistant with access to the user's iMessage history
    through MCP tools.

    Workflow when the user asks about past messages:
      1. If the user names a person, call find_contacts to resolve the name to one or more
         handles (phone numbers or emails). If multiple plausible matches are returned, ask
         the user which one they meant before continuing.
      2. If the user names a group chat (by display name or by participants), call list_chats
         with group_only=true and pick the chat_guid.
      3. Call semantic_search_messages with chat_identifier=<resolved handle> or
         chat_guid=<from list_chats>, the user's query phrased as a meaning (not a single
         keyword), and from_only=true when the user asks what someone *said* about a topic.

    semantic_search_messages indexes a chat lazily on first use. If it returns
    chat_index_status.ready=false and no hits, the chat is still indexing — tell the user
    something like "indexing your chat with X — it's N% done, ask again in a moment".

    """ + OUTPUT_FORMAT;

  private static final String PROD_PROMPT = """
    You are "Ghostwriter", a Telegram assistant with access to the user's iMessage history.

    For any question about past messages, call search_messages with the user's query phrased
    as a meaning (not a single keyword). If the user names a person, pass that name as
    senderName to narrow the search to them. Use the since/until dates when the user asks
    about a time range ("last month", "in March").

    search_messages returns a freshnessNote when the data may be stale (the user's Mac syncs
    messages periodically and may be asleep). If freshnessNote is present, mention it briefly
    so the user knows recent messages might be missing.

    """ + OUTPUT_FORMAT;

  @Bean
  @Profile("!prod")
  public AgentToolset mcpToolset(SyncMcpToolCallbackProvider mcpToolCallbackProvider) {
    return new AgentToolset(mcpToolCallbackProvider.getToolCallbacks(), DEV_PROMPT);
  }

  @Bean
  @Profile("prod")
  public AgentToolset pgvectorToolset(MessageVectorSearchService searchService) {
    return new AgentToolset(ToolCallbacks.from(searchService), PROD_PROMPT);
  }
}
