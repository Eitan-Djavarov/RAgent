using Microsoft.EntityFrameworkCore;
using TechDocIntelligence.Backend.Clients;
using TechDocIntelligence.Backend.Data;
using TechDocIntelligence.Backend.Models.DTOs;

namespace TechDocIntelligence.Backend.Services;

internal static class IncidentMapping
{
    public static Dictionary<string, string?> BuildMetadata(
        IncidentEntity entity,
        IReadOnlyList<string>? subsystemTags)
    {
        var metadata = new Dictionary<string, string?>
        {
            ["type"] = "incident",
            ["systemName"] = entity.SystemName,
            ["severity"] = entity.Severity.ToString(),
        };

        if (subsystemTags is { Count: > 0 })
        {
            metadata["subsystemTags"] = string.Join(",", subsystemTags.Select(tag => tag.Trim())
                .Where(tag => !string.IsNullOrWhiteSpace(tag)));
        }

        return metadata;
    }

    public static string BuildIngestContent(
        IncidentEntity entity,
        IReadOnlyList<string>? subsystemTags)
    {
        var tags = subsystemTags is { Count: > 0 }
            ? string.Join(", ", subsystemTags)
            : "n/a";

        return $"""
            Incident Report
            Title: {entity.Title}
            System: {entity.SystemName}
            Severity: {entity.Severity}
            Subsystem Tags: {tags}
            Description:
            {entity.Description}
            """;
    }

    public static IncidentReportDto Map(IncidentEntity entity, int chunksIndexed) =>
        new(
            entity.Id,
            entity.Title,
            entity.Description,
            entity.SystemName,
            entity.Severity,
            entity.CreatedAt,
            entity.IndexedAt,
            chunksIndexed,
            entity.IngestionMessage);

    public static async Task<IReadOnlyList<IncidentCitationDto>> ApplyMinSeverityFilterAsync(
        AppDbContext dbContext,
        IReadOnlyList<IncidentCitationDto> citations,
        string? minSeverity,
        CancellationToken cancellationToken)
    {
        if (!AiResponseMapper.TryParseSeverity(minSeverity, out var minimum)
            || citations.Count == 0)
        {
            return citations;
        }

        var documentIds = citations
            .Select(citation => Guid.TryParse(citation.DocumentId, out var id) ? id : Guid.Empty)
            .Where(id => id != Guid.Empty)
            .Distinct()
            .ToList();

        if (documentIds.Count == 0)
        {
            return citations;
        }

        var severityById = await dbContext.Incidents
            .AsNoTracking()
            .Where(incident => documentIds.Contains(incident.Id))
            .Select(incident => new { incident.Id, incident.Severity })
            .ToDictionaryAsync(row => row.Id, row => row.Severity, cancellationToken);

        return citations
            .Where(citation =>
            {
                if (!Guid.TryParse(citation.DocumentId, out var id))
                {
                    return true;
                }

                if (!severityById.TryGetValue(id, out var severity))
                {
                    return true;
                }

                return severity >= minimum;
            })
            .ToList();
    }
}
