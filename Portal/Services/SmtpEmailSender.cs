using MailKit.Net.Smtp;
using MailKit.Security;
using Microsoft.AspNetCore.Identity.UI.Services;
using MimeKit;

namespace GridWitness.Portal.Services;

public sealed class SmtpSettings
{
    public string Host { get; set; } = "";
    public int Port { get; set; } = 587;
    public string User { get; set; } = "";
    public string Password { get; set; } = "";
    public string FromEmail { get; set; } = "no-reply@twinscrollgridbalancer.co.uk";
    public string FromName { get; set; } = "GridWitness";
    public bool UseStartTls { get; set; } = true;

    // Both a host and a token are required to actually send; otherwise we log the message (incl. the
    // confirmation link) instead — so a missing secret degrades gracefully rather than silently failing.
    public bool IsConfigured => !string.IsNullOrWhiteSpace(Host) && !string.IsNullOrWhiteSpace(Password);
}

/// <summary>
/// Identity's <see cref="IEmailSender"/> backed by MailKit. When no SMTP host is configured (local
/// dev), it logs the message — including the email-confirmation link — instead of sending, so the
/// confirmation flow can be walked end to end without a mail server.
/// </summary>
public sealed class SmtpEmailSender : IEmailSender
{
    private readonly SmtpSettings _cfg;
    private readonly ILogger<SmtpEmailSender> _log;

    public SmtpEmailSender(Microsoft.Extensions.Options.IOptions<SmtpSettings> cfg, ILogger<SmtpEmailSender> log)
    {
        _cfg = cfg.Value;
        _log = log;
    }

    public async Task SendEmailAsync(string email, string subject, string htmlMessage)
    {
        if (!_cfg.IsConfigured)
        {
            _log.LogInformation(
                "[email:dev] SMTP not configured; would send to {Email} — {Subject}\n{Body}",
                email, subject, htmlMessage);
            return;
        }

        // Never let an SMTP problem break the caller (e.g. registration). Log and move on — the user
        // can resend the confirmation later; unconfirmed accounts can still contribute by design.
        try
        {
            var msg = new MimeMessage();
            msg.From.Add(new MailboxAddress(_cfg.FromName, _cfg.FromEmail));
            msg.To.Add(MailboxAddress.Parse(email));
            msg.Subject = subject;
            msg.Body = new BodyBuilder { HtmlBody = htmlMessage }.ToMessageBody();

            using var client = new SmtpClient();
            var secureOption = _cfg.UseStartTls ? SecureSocketOptions.StartTls : SecureSocketOptions.SslOnConnect;
            await client.ConnectAsync(_cfg.Host, _cfg.Port, secureOption);
            if (!string.IsNullOrEmpty(_cfg.User))
                await client.AuthenticateAsync(_cfg.User, _cfg.Password);
            await client.SendAsync(msg);
            await client.DisconnectAsync(true);
            _log.LogInformation("Sent '{Subject}' to {Email}", subject, email);
        }
        catch (Exception ex)
        {
            _log.LogError(ex, "Failed to send '{Subject}' to {Email} — continuing without it.", subject, email);
        }
    }
}
