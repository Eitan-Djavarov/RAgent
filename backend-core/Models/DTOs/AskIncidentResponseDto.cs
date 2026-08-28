using System.Text.Json.Serialization;

namespace TechDocIntelligence.Backend.Models.DTOs;

public sealed record SqlQueryResultDto(
    [property: JsonPropertyName("query")] string Query,
    [property: JsonPropertyName("rowCount")] int RowCount,
    [property: JsonPropertyName("columns")] IReadOnlyList<string> Columns,
    [property: JsonPropertyName("rows")] IReadOnlyList<Dictionary<string, object?>> Rows,
    [property: JsonPropertyName("interpretation")] string Interpretation);

/// <summary>
/// Unified ask/analyze response including agentic router metadata.
/// </summary>
public sealed record AskIncidentResponseDto(
    string Summary,
    string RootCause,
    string ActionItems,
    IReadOnlyList<IncidentCitationDto> Citations,
    double LatencyMs,
    string? ToolUsed = null,
    SqlQueryResultDto? SqlQueryResult = null,
    string? Answer = null,
    string? RetrievalMode = null,
    bool Cached = false,
    string? SessionId = null,
    string? OriginalQuery = null,
    string? RewrittenQuery = null,
    double? FaithfulnessScore = null,
    bool? IsGrounded = null,
    IReadOnlyList<string>? UnsupportedClaims = null);
