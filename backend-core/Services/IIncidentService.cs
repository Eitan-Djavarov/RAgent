using Microsoft.AspNetCore.Http;
using TechDocIntelligence.Backend.Models.DTOs;

namespace TechDocIntelligence.Backend.Services;

public interface IIncidentService
{
    Task<IncidentReportDto> CreateAsync(
        CreateIncidentRequestDto request,
        CancellationToken cancellationToken = default);

    Task<IncidentReportDto?> GetByIdAsync(Guid id, CancellationToken cancellationToken = default);

    Task<IReadOnlyList<IncidentReportDto>> ListAsync(CancellationToken cancellationToken = default);

    Task<AskIncidentResponseDto> AnalyzeIncidentAsync(
        AskIncidentQueryDto request,
        CancellationToken cancellationToken = default);

    Task<FileIngestResponseDto> UploadDocumentAsync(
        IFormFile file,
        string? title,
        string system,
        string severity,
        string? subsystemTags,
        CancellationToken cancellationToken = default);

    Task<DocumentDeleteResponseDto> DeleteAsync(
        Guid id,
        CancellationToken cancellationToken = default);
}
