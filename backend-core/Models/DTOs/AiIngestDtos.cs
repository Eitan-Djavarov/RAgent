using System.Text.Json.Serialization;

namespace TechDocIntelligence.Backend.Models.DTOs;

public sealed record AiIngestRequestDto(
    [property: JsonPropertyName("documentId")] string DocumentId,
    [property: JsonPropertyName("title")] string Title,
    [property: JsonPropertyName("content")] string Content,
    [property: JsonPropertyName("metadata")] Dictionary<string, string?> Metadata);

public sealed record AiIngestResponseDto(
    [property: JsonPropertyName("success")] bool Success,
    [property: JsonPropertyName("documentId")] string DocumentId,
    [property: JsonPropertyName("chunksCount")] int ChunksCount,
    [property: JsonPropertyName("message")] string Message);

public sealed record FileIngestResponseDto(
    [property: JsonPropertyName("success")] bool Success,
    [property: JsonPropertyName("documentId")] string DocumentId,
    [property: JsonPropertyName("chunkCount")] int ChunkCount,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("message")] string Message,
    [property: JsonPropertyName("title")] string? Title = null,
    [property: JsonPropertyName("systemName")] string? SystemName = null,
    [property: JsonPropertyName("severity")] string? Severity = null);
