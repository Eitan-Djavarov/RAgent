using System.Text.Json.Serialization;

namespace TechDocIntelligence.Backend.Models.DTOs;

public sealed record AiQueryRequestDto(
    [property: JsonPropertyName("query")] string Query,
    [property: JsonPropertyName("topK")] int TopK,
    [property: JsonPropertyName("filterMetadata")] Dictionary<string, string?>? FilterMetadata,
    [property: JsonPropertyName("structured")] bool Structured = true,
    [property: JsonPropertyName("sessionId")] string? SessionId = null);

public sealed record AiQueryResponseDto(
    [property: JsonPropertyName("answer")] string Answer,
    [property: JsonPropertyName("sources")] IReadOnlyList<AiSourceCitationDto> Sources,
    [property: JsonPropertyName("latencyMs")] double LatencyMs,
    [property: JsonPropertyName("analysis")] AiStructuredAnalysisDto? Analysis,
    [property: JsonPropertyName("retrievalMode")] string? RetrievalMode,
    [property: JsonPropertyName("toolUsed")] string? ToolUsed = null,
    [property: JsonPropertyName("sqlQueryResult")] AiSqlQueryResultDto? SqlQueryResult = null,
    [property: JsonPropertyName("summary")] string? Summary = null,
    [property: JsonPropertyName("rootCause")] string? RootCause = null,
    [property: JsonPropertyName("actionItems")] string? ActionItems = null,
    [property: JsonPropertyName("citations")] IReadOnlyList<AiSourceCitationDto>? Citations = null,
    [property: JsonPropertyName("cached")] bool Cached = false,
    [property: JsonPropertyName("sessionId")] string? SessionId = null,
    [property: JsonPropertyName("originalQuery")] string? OriginalQuery = null,
    [property: JsonPropertyName("rewrittenQuery")] string? RewrittenQuery = null,
    [property: JsonPropertyName("faithfulnessScore")] double? FaithfulnessScore = null,
    [property: JsonPropertyName("isGrounded")] bool? IsGrounded = null,
    [property: JsonPropertyName("unsupportedClaims")] IReadOnlyList<string>? UnsupportedClaims = null);

public sealed record AiSqlQueryResultDto(
    [property: JsonPropertyName("query")] string Query,
    [property: JsonPropertyName("rowCount")] int RowCount,
    [property: JsonPropertyName("columns")] IReadOnlyList<string>? Columns,
    [property: JsonPropertyName("rows")] IReadOnlyList<Dictionary<string, object?>>? Rows,
    [property: JsonPropertyName("interpretation")] string? Interpretation);

public sealed record AiStructuredAnalysisDto(
    [property: JsonPropertyName("executiveSummary")] string ExecutiveSummary,
    [property: JsonPropertyName("rootCauseAnalysis")] string RootCauseAnalysis,
    [property: JsonPropertyName("recommendedMitigations")] string RecommendedMitigations,
    [property: JsonPropertyName("sourceCitations")] IReadOnlyList<AiSourceCitationDto>? SourceCitations);

public sealed record AiSourceCitationDto(
    [property: JsonPropertyName("documentId")] string DocumentId,
    [property: JsonPropertyName("chunkText")] string ChunkText,
    [property: JsonPropertyName("score")] double Score,
    [property: JsonPropertyName("citationIndex")] int? CitationIndex = null,
    [property: JsonPropertyName("docId")] string? DocId = null,
    [property: JsonPropertyName("system")] string? System = null,
    [property: JsonPropertyName("severity")] string? Severity = null,
    [property: JsonPropertyName("parentId")] string? ParentId = null);
