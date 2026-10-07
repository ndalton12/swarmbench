/* Minimal PID 1: reaps orphaned processes, exits on SIGTERM/SIGINT, and keeps a lease.
 *
 * The host renews the lease by touching LEASE_FILE (root-only) every few seconds.
 * If it is not renewed for LEASE seconds (the run's process died without cleaning
 * up), init kills every process in the container and exits, so the container stops.
 * Until the first renewal, the lease runs from container start plus FIRST_GRACE.
 * Usage: /sbin/init [lease-seconds [first-grace-seconds]]
 */
#include <signal.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define LEASE_FILE "/var/backups/.lease"
#define CHECK_EVERY 15

static volatile sig_atomic_t tick = 0;

static void on_child(int sig) { (void)sig; }
static void on_alarm(int sig) { (void)sig; tick = 1; }
static void on_term(int sig) { (void)sig; _exit(0); }

int main(int argc, char **argv) {
    long lease = argc > 1 ? atol(argv[1]) : 300;
    long first_grace = argc > 2 ? atol(argv[2]) : 900;
    time_t started = time(NULL);
    sigset_t block, wait_mask;

    sigemptyset(&block);
    sigaddset(&block, SIGCHLD);
    sigaddset(&block, SIGALRM);
    /* these stay blocked except inside sigsuspend, so no signal is missed between
       reaping and waiting */
    sigprocmask(SIG_BLOCK, &block, &wait_mask);
    sigdelset(&wait_mask, SIGCHLD);
    sigdelset(&wait_mask, SIGALRM);
    signal(SIGCHLD, on_child);
    signal(SIGALRM, on_alarm);
    signal(SIGTERM, on_term);
    signal(SIGINT, on_term);
    alarm(lease < CHECK_EVERY ? 1 : CHECK_EVERY);

    for (;;) {
        while (waitpid(-1, NULL, WNOHANG) > 0) {
        }
        if (tick) {
            struct stat st;
            time_t renewed = started + first_grace - lease;
            tick = 0;
            if (stat(LEASE_FILE, &st) == 0) {
                renewed = st.st_mtime;
            }
            if (lease > 0 && time(NULL) - renewed > lease) {
                kill(-1, SIGKILL);
                _exit(0);
            }
            alarm(lease < CHECK_EVERY ? 1 : CHECK_EVERY);
        }
        sigsuspend(&wait_mask);
    }
}
