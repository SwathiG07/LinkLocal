#include<stdio.h>
#include<stdlib.h>
int main()
{
    FILE *fp;
    char s;
    fp=fopen("b.txt","r");
    fseek(fp,-10,SEEK_END);
    char c=fgetc(fp);
    printf("%c",c);
    printf("\n");
    while(!feof(fp))
    {
    s=fgetc(fp);
    printf("%c",s);
    }
    fclose(fp);
}