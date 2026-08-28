namespace TechDocIntelligence.Backend.Models.DTOs;

public sealed record HealthResponseDto(
    string Status,
    string Service,
    DateTimeOffset Timestamp);
