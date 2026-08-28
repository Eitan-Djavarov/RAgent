using System.Text.Json.Serialization;

namespace TechDocIntelligence.Backend.Models.DTOs;

public sealed record DocumentDeleteResponseDto(
    [property: JsonPropertyName("success")] bool Success,
    [property: JsonPropertyName("documentId")] string DocumentId,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("vectorsDeleted")] int VectorsDeleted,
    [property: JsonPropertyName("postgresDeleted")] bool PostgresDeleted,
    [property: JsonPropertyName("cacheEntriesInvalidated")] int CacheEntriesInvalidated,
    [property: JsonPropertyName("message")] string Message);

public sealed record ProblemDetailsDto(
    string Type,
    string Title,
    int Status,
    string Detail,
    string? TraceId,
    string? ErrorCode = null,
    string? Reason = null,
    int? RetryAfterSeconds = null);
