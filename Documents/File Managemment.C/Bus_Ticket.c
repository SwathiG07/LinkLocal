#include<stdio.h>
#include<string.h>
#include<stdlib.h>

#define MAX_DATE 20
#define MAX_NAME 50
#define MAX_BUS 10


typedef struct 
{
    int bus_no;
    char driver[MAX_NAME];
    char cond[MAX_NAME];
    char date[MAX_DATE];
    int seats;
}Bus;


void add(FILE *fp)
{
    Bus bus;
    printf("enter bus number");
    scanf("%d",&bus.bus_no);
    getchar();
    printf("enter driver name");
    fgets(bus.driver,MAX_NAME,stdin);
    bus.driver[strcspn(bus.driver, "\n")] = 0;
    printf("enter driver name");
    fgets(bus.cond,MAX_NAME,stdin);
    bus.cond[strcspn(bus.cond, "\n")] = 0;
    printf("enter date");
    scanf("%s",bus.date);
    printf("enter seats avaailable");
    scanf("%d",&bus.seats);
    fseek(fp, 0, SEEK_END);
    fwrite(&bus,sizeof(Bus),1,fp);
}

void view(FILE *fp)
{
    Bus bus;
    rewind(fp);
    printf("BUS DETAILS\n");
    while(fread(&bus,sizeof(Bus),1,fp))
    {
    printf("%-20d %-20s %-10s %-10s %10d\n",bus.bus_no,bus.driver,bus.cond,bus.date,bus.seats);
    }
}

int main()
{
    FILE *fp;
    fp=fopen("c.dat","rb+");
    if(fp==NULL)
    {
        fp=fopen("c.dat","wb+");
        if(fp==NULL)
        {
            printf("Error");
            return 1;
        }
    }
    int choice;
    do
    {
        printf("enter choice 1.add 2.view 3.exit");
        scanf("%d",&choice);
        switch(choice)
        {
            case 1:
                add(fp);
                break;
            case 2:
                view(fp);
                break;
            case 3:
                printf("exit");
                break;
            default:
            printf("done");
        }
    }while(choice!=3);
    fclose(fp);
    return 0;
}