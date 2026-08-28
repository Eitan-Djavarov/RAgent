using TechDocIntelligence.Backend.Models.DTOs;

namespace TechDocIntelligence.Backend.Clients;

public interface IAiServiceClient
{
    Task<AiIngestResponseDto> IngestAsync(
        AiIngestRequestDto request,
        CancellationToken cancellationToken = default);

    Task<FileIngestResponseDto> IngestFileAsync(
        Stream fileStream,
        string fileName,
        string? contentType,
        string? title,
        string system,
        string severity,
        string? subsystemTags,
        CancellationToken cancellationToken = default);

    Task<AiQueryResponseDto> QueryAsync(
        AiQueryRequestDto request,
        CancellationToken cancellationToken = default);

    Task<AskIncidentResponseDto> QueryIncidentsAsync(
        AskIncidentQueryDto request,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Opens an SSE stream from the AI ask/stream endpoint. Caller must dispose the response.
    /// </summary>
    Task<HttpResponseMessage> StreamQueryIncidentsAsync(
        AskIncidentQueryDto request,
        CancellationToken cancellationToken = default);

    Task<bool> IsHealthyAsync(CancellationToken cancellationToken = default);
}
