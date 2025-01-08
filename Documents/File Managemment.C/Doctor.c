#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// Structure to store doctor information
struct Doctor {
    int doctorID;
    char name[50];
    char specialization[50];
    char availabilityTime[30];
};

// File to store doctor records
const char *FILENAME = "doctor_database.dat";

// Function to display a doctor's information
void displayDoctor(struct Doctor d) {
    printf("\nDoctor ID: %d\nName: %s\nSpecialization: %s\nAvailability Time: %s\n", 
           d.doctorID, d.name, d.specialization, d.availabilityTime);
}

// Function to add a doctor record
void addDoctor() {
    FILE *file = fopen(FILENAME, "ab+");
    if (!file) { printf("Error opening file\n"); return; }

    struct Doctor d;
    printf("Enter Doctor ID: "); scanf("%d", &d.doctorID);
    printf("Enter Name: "); scanf(" %[^\n]", d.name);
    printf("Enter Specialization: "); scanf(" %[^\n]", d.specialization);
    printf("Enter Availability Time: "); scanf(" %[^\n]", d.availabilityTime);
    fwrite(&d, sizeof(d), 1, file);
    fclose(file);
    printf("Doctor added successfully!\n");
}

// Function to view all doctor records
void viewDoctors() {
    FILE *file = fopen(FILENAME, "rb");
    if (!file) { printf("No records found.\n"); return; }

    struct Doctor d;
    while (fread(&d, sizeof(d), 1, file)) {
        displayDoctor(d);
    }
    fclose(file);
}

// Function to search for a doctor by ID
void searchDoctor() {
    FILE *file = fopen(FILENAME, "rb");
    if (!file) { printf("No records found.\n"); return; }

    int doctorID;
    printf("Enter Doctor ID to search: "); scanf("%d", &doctorID);
    
    struct Doctor d;
    while (fread(&d, sizeof(d), 1, file)) {
        if (d.doctorID == doctorID) {
            displayDoctor(d);
            fclose(file);
            return;
        }
    }
    printf("Doctor not found.\n");
    fclose(file);
}

// Function to update a doctor's record
void updateDoctor() {
    FILE *file = fopen(FILENAME, "rb+");
    if (!file) { printf("No records found.\n"); return; }

    int doctorID;
    printf("Enter Doctor ID to update: "); scanf("%d", &doctorID);
    
    struct Doctor d;
    while (fread(&d, sizeof(d), 1, file)) {
        if (d.doctorID == doctorID) {
            printf("Enter New Name: "); scanf(" %[^\n]", d.name);
            printf("Enter New Specialization: "); scanf(" %[^\n]", d.specialization);
            printf("Enter New Availability Time: "); scanf(" %[^\n]", d.availabilityTime);
            
            fseek(file, -sizeof(d), SEEK_CUR);
            fwrite(&d, sizeof(d), 1, file);
            printf("Doctor updated successfully!\n");
            fclose(file);
            return;
        }
    }
    printf("Doctor not found.\n");
    fclose(file);
}

// Function to delete a doctor's record
void deleteDoctor() {
    FILE *file = fopen(FILENAME, "rb");
    if (!file) { printf("No records found.\n"); return; }

    FILE *tempFile = fopen("temp.dat", "wb");
    if (!tempFile) { printf("Error creating temporary file\n"); fclose(file); return; }

    int doctorID;
    printf("Enter Doctor ID to delete: "); scanf("%d", &doctorID);
    
    struct Doctor d;
    int found = 0;
    while (fread(&d, sizeof(d), 1, file)) {
        if (d.doctorID != doctorID) {
            fwrite(&d, sizeof(d), 1, tempFile);
        } else {
            found = 1;
        }
    }

    fclose(file);
    fclose(tempFile);
    remove(FILENAME);
    rename("temp.dat", FILENAME);
    printf(found ? "Doctor deleted successfully!\n" : "Doctor not found.\n");
}

// Main menu function
void menu() {
    int choice;
    while (1) {
        printf("\n--- Doctor Management System ---\n");
        printf("1. Add Doctor\n2. View Doctors\n3. Search Doctor\n4. Update Doctor\n5. Delete Doctor\n0. Exit\nChoice: ");
        scanf("%d", &choice);
        switch (choice) {
            case 1: addDoctor(); break;
            case 2: viewDoctors(); break;
            case 3: searchDoctor(); break;
            case 4: updateDoctor(); break;
            case 5: deleteDoctor(); break;
            case 0: exit(0);
            default: printf("Invalid choice.\n");
        }
    }
}

// Main function
int main() {
    menu();
    return 0;
}

