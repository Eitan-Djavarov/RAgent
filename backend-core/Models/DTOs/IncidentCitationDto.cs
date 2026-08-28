namespace TechDocIntelligence.Backend.Models.DTOs;

public sealed record IncidentCitationDto(
    string DocumentId,
    string ChunkText,
    double Score,
    int? CitationIndex = null,
    string? DocId = null,
    string? System = null,
    string? Severity = null,
    string? ParentId = null);
