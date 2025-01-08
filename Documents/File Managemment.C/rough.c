#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_NAME 50
#define MAX_BUSES 5
#define MAX_DATE 11

typedef struct {
    int bus_number;
    char driver_name[MAX_NAME];
    char conductor_name[MAX_NAME];
    int seats_available;
    char date[MAX_DATE];
} Bus;

void add_bus(FILE *file) {
    Bus bus;

    printf("Enter Bus Number: ");
    scanf("%d", &bus.bus_number);

    printf("Enter Driver Name: ");
    getchar();
    fgets(bus.driver_name, MAX_NAME, stdin);
    bus.driver_name[strcspn(bus.driver_name, "\n")] = 0;

    printf("Enter Conductor Name: ");
    fgets(bus.conductor_name, MAX_NAME, stdin);
    bus.conductor_name[strcspn(bus.conductor_name, "\n")] = 0;

    printf("Enter Number of Seats Available: ");
    scanf("%d", &bus.seats_available);

    printf("Enter Date (DD-MM-YYYY): ");
    scanf("%s", bus.date);

    fseek(file, 0, SEEK_END);
    fwrite(&bus, sizeof(Bus), 1, file);

    printf("Bus details added successfully!\n");
}

void view_buses(FILE *file) {
    Bus bus;
    rewind(file);

    printf("\nBus Details:\n");
    printf("%-10s %-20s %-20s %-10s %-12s\n", "Bus No", "Driver Name", "Conductor Name", "Seats", "Date");
    printf("----------------------------------------------------------------------\n");

    while (fread(&bus, sizeof(Bus), 1, file)) {
        printf("%-10d %-20s %-20s %-10d %-12s\n", bus.bus_number, bus.driver_name, bus.conductor_name, bus.seats_available, bus.date);
    }
}

int main() {
    FILE *file;
    int choice;

    file = fopen("buses.dat", "rb+");
    if (file == NULL) {
        file = fopen("buses.dat", "wb+");
        if (file == NULL) {
            perror("Error opening file");
            return 1;
        }
    }

    do {
        printf("\nBus Management System\n");
        printf("1. Add Bus\n");
        printf("2. View Buses\n");
        printf("3. Exit\n");
        printf("Enter your choice: ");
        scanf("%d", &choice);

        switch (choice) {
            case 1:
                add_bus(file);
                break;
            case 2:
                view_buses(file);
                break;
            case 3:
                printf("Exiting...\n");
                break;
            default:
                printf("Invalid choice! Please try again.\n");
        }
    } while (choice != 3);

    fclose(file);
    return 0;
}
