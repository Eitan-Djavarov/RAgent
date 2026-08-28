namespace TechDocIntelligence.Backend.Models.DTOs;

public sealed record IncidentReportDto(
    Guid Id,
    string Title,
    string Description,
    string SystemName,
    IncidentSeverity Severity,
    DateTimeOffset CreatedAt,
    DateTimeOffset? IndexedAt = null,
    int ChunksIndexed = 0,
    string? IngestionMessage = null);
