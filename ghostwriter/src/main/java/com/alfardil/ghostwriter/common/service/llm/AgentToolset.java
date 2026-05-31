package com.alfardil.ghostwriter.common.service.llm;

import org.springframework.ai.tool.ToolCallback;

/**
 * The tools + system prompt the {@link LLMClient} runs with. Supplied per Spring profile by
 * {@link ToolConfig}: the default (dev) profile bridges the Mac's MCP server, while {@code prod}
 * uses the in-process pgvector search tool so the Mac is out of the request path (DEPLOYMENT.md).
 */
public record AgentToolset(ToolCallback[] callbacks, String systemPrompt) {}
